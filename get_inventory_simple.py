#!/usr/bin/env python3
# get_inventory_simple.py
# Minimal CLI: either --location or --bbox; always merges NSI; no post-processing.

"""
README: Building Inventory Generator with NSI Integration

OVERVIEW:
This script fetches building footprints for a specified location or bounding box,
merges them with the National Structure Inventory (NSI) data to enrich the attributes,
and saves the resulting inventory to a GeoJSON file.

USAGE:
    # Using a location name:
    python get_inventory_simple.py --location "Northridge, Los Angeles, CA"
    
    # Using a bounding box (lon_min, lat_min, lon_max, lat_max):
    python get_inventory_simple.py --bbox -118.5 34.2 -118.4 34.3

REQUIREMENTS:
    pip install --upgrade git+https://github.com/NHERI-SimCenter/BrailsPlusPlus

WORKFLOW:
    1. Fetch building footprints from OpenStreetMap (OSM) or USA Footprint database
       - Tries OSM first for speed
       - Falls back to USA footprints if OSM fails
       - Auto-tiles large bounding boxes into 4 quadrants if needed
    
    2. Merge with National Structure Inventory (NSI) data
       - Enriches footprints with attributes like YearBuilt, NumberOfStories, etc.
       - Processes in chunks of 1500 assets for better performance
       - Uses retry logic for network reliability
    
    3. Save to GeoJSON file
       - Output filename based on location name or bbox coordinates
       - Format: inventory_<location>_nsi.geojson or inventory_bbox_<coords>_nsi.geojson

OUTPUT:
    GeoJSON file containing building inventory with merged NSI attributes including:
    - Geometry (building footprints)
    - YearBuilt
    - NumberOfStories
    - StructureType
    - OccupancyClass
    - And other NSI attributes

FEATURES:
    - Automatic retry logic for network requests
    - Chunked NSI merging for large inventories
    - Automatic fallback strategies (OSM → tiling → USA footprints)
    - Robust error handling across different BRAILS versions
"""



import argparse
from pathlib import Path
import random
import sys
import time
import json, tempfile
import time

# Requires: pip install --upgrade git+https://github.com/NHERI-SimCenter/BrailsPlusPlus
from brails.utils.importer import Importer


# -------------------- small utilities --------------------

def add_asset_safe(inventory, key, asset):
    """
    Call AssetInventory.add_asset in a way that works across BRAILS variants.
    
    Different versions of BRAILS have different signatures for add_asset():
    - Some require (key, asset)
    - Others only accept (asset)
    This function tries both to ensure compatibility.
    
    Args:
        inventory: AssetInventory object
        key: Asset ID/key
        asset: Asset object to add
    """
    try:
        inventory.add_asset(key, asset)   # some builds require (key, asset)
    except TypeError:
        inventory.add_asset(asset)        # others accept (asset) only


def with_retries(fn, retries=3, delay=2.0, *args, **kwargs):
    """
    Execute a function with automatic retry logic for network resilience.
    
    Args:
        fn: Function to execute
        retries: Number of retry attempts (default: 3)
        delay: Delay in seconds between retries (default: 2.0)
        *args, **kwargs: Arguments to pass to the function
    
    Returns:
        Result of the function call
    
    Raises:
        Last exception encountered if all retries fail
    """
    last = None
    for i in range(retries):
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            last = e
            if i < retries - 1:
                time.sleep(delay)
    raise last


def sample_inventory(inventory, n):
    """
    Down-sample inventory to n assets (robust across BRAILS versions).
    
    Args:
        inventory: AssetInventory object
        n: Number of assets to sample
    
    Returns:
        AssetInventory containing n randomly selected assets
    
    Note:
        - Tries built-in get_random_sample() first
        - Falls back to manual random sampling if needed
        - Returns original inventory if n >= total assets
    """
    try:
        return inventory.get_random_sample(1, n)
    except Exception:
        pass

    inv = inventory.inventory  # {id: Asset}
    if not inv or n >= len(inv):
        return inventory

    keep = set(random.sample(list(inv.keys()), n))
    importer = Importer()
    AssetInventory = importer.get_class("AssetInventory")
    out = AssetInventory()
    for k in keep:
        add_asset_safe(out, k, inv[k])    # <-- use helper
    return out

def build_boundary(importer, location=None, bbox=None):
    """
    Create a RegionBoundary object from either a location name or bounding box.
    
    Args:
        importer: Importer instance for getting BRAILS classes
        location: String location name (e.g., "Northridge, Los Angeles, CA")
        bbox: Tuple of (lon_min, lat_min, lon_max, lat_max)
    
    Returns:
        RegionBoundary object configured for the specified area
    
    Raises:
        ValueError: If neither location nor bbox is provided
    """
    RegionBoundary = importer.get_class("RegionBoundary")
    if bbox:
        lon_min, lat_min, lon_max, lat_max = bbox
        # Use the tuple that current BRAILS builds accept:
        return RegionBoundary({"type": "locationPolygon",
                               "data": (lon_min, lat_min, lon_max, lat_max)})
    if location:
        return RegionBoundary({"type": "locationName", "data": location})
    raise ValueError("Provide either --location or --bbox.")



def fetch_footprints(importer, scraper, location=None, bbox=None):
    """
    Fetch building footprints with automatic fallback strategies.
    
    Strategy:
    1. Try OSM footprint scraper for the entire region
    2. If that fails with bbox, split into 4 quadrants and retry
    3. If still fails, fall back to USA_FootprintScraper
    
    Args:
        importer: Importer instance for getting BRAILS classes
        scraper: Footprint scraper instance (typically OSM_FootprintScraper)
        location: String location name (e.g., "Northridge, Los Angeles, CA")
        bbox: Tuple of (lon_min, lat_min, lon_max, lat_max)
    
    Returns:
        AssetInventory containing building footprints
    
    Note:
        - Uses retry logic for network resilience
        - Automatic tiling for large areas
        - Seamless fallback to alternative data sources
    """
    def run_once(_scraper, _region, retries=3, delay=2.5):
        last = None
        for _ in range(retries):
            try:
                return _scraper.get_footprints(_region)
            except Exception as e:
                last = e
                time.sleep(delay)
        raise last

    RegionBoundary = importer.get_class("RegionBoundary")

    # Location path
    if bbox is None:
        region = build_boundary(importer, location=location, bbox=None)
        return run_once(scraper, region)

    # BBox path
    lon_min, lat_min, lon_max, lat_max = bbox
    region = build_boundary(importer, bbox=bbox)

    # Try OSM once
    try:
        return run_once(scraper, region)
    except Exception as e_first:
        # Auto tile into 4 and try OSM again
        try:
            mid_lon = (lon_min + lon_max) / 2.0
            mid_lat = (lat_min + lat_max) / 2.0
            tiles = [
                (lon_min, lat_min, mid_lon,  mid_lat),
                (mid_lon,  lat_min, lon_max, mid_lat),
                (lon_min,  mid_lat, mid_lon,  lat_max),
                (mid_lon,  mid_lat, lon_max,  lat_max),
            ]
            AssetInventory = importer.get_class("AssetInventory")
            out_inv = AssetInventory()
            for t in tiles:
                sub_region = RegionBoundary({"type": "locationPolygon", "data": t})
                sub_inv = run_once(scraper, sub_region, retries=2, delay=3.0)
                for k, asset in sub_inv.inventory.items():
                    add_asset_safe(out_inv, k, asset)
            if len(out_inv.inventory) > 0:
                return out_inv
            else:
                raise e_first
        except Exception:
            # Final fallback: switch to USA footprints for the same bbox
            USA_FootprintScraper = importer.get_class("USA_FootprintScraper")
            usa_scraper = USA_FootprintScraper({"length": "ft"})
            usa_region = RegionBoundary({"type": "locationPolygon",
                                         "data": (lon_min, lat_min, lon_max, lat_max)})
            return run_once(usa_scraper, usa_region, retries=2, delay=3.0)
# -------------------- NSI merge in chunks --------------------

def chunked_merge_nsi(inventory, length_unit="ft", chunk_size=1500):
    """
    Split inventory into chunks and merge with NSI data for better performance.
    
    Processing large inventories in one go can be slow and prone to timeout.
    This function processes assets in batches, providing progress feedback.
    
    Args:
        inventory: AssetInventory object to enrich
        length_unit: Unit for measurements (default: "ft")
        chunk_size: Number of assets to process per batch (default: 1500)
    
    Returns:
        AssetInventory with NSI data merged for all assets
    
    NSI Attributes Added:
        - YearBuilt: Year the structure was built
        - NumberOfStories: Building height in stories
        - StructureType: Type of structure (e.g., wood frame, concrete)
        - OccupancyClass: Building use (residential, commercial, etc.)
        - And other NSI fields depending on availability
    
    Note:
        - Processes sequentially for stability
        - Uses retry logic for each chunk
        - Provides progress updates during processing
    """
    inv_dict = inventory.inventory
    if not inv_dict:
        return inventory

    importer = Importer()
    AssetInventory = importer.get_class("AssetInventory")
    NSI_Parser = importer.get_class("NSI_Parser")

    keys = list(inv_dict.keys())
    out = AssetInventory()
    print(f"Merging NSI in chunks of ~{chunk_size} (total {len(keys)} assets) ...")
    for i in range(0, len(keys), chunk_size):
        batch = keys[i:i + chunk_size]
        sub = AssetInventory()
        for k in batch:
            add_asset_safe(sub, k, inv_dict[k])  # <-- use helper

        nsi = NSI_Parser()
        sub = with_retries(nsi.get_filtered_data_given_inventory, 3, 2.0, sub, length_unit)

        for k, asset in sub.inventory.items():
            add_asset_safe(out, k, asset)        # <-- use helper

        print(f"  NSI merged: {min(i + chunk_size, len(keys))}/{len(keys)}")
    return out

# -------------------- main --------------------
def main():
    """
    Main entry point for the building inventory generator.
    
    Workflow:
    1. Parse command-line arguments (--location or --bbox)
    2. Fetch building footprints using OSM or USA scraper
    3. Merge with NSI data to enrich attributes
    4. Save results to GeoJSON file
    
    Command-line Arguments:
        --location: Location name (e.g., "Northridge, Los Angeles, CA")
        --bbox: Bounding box as lon_min lat_min lon_max lat_max
    
    Output:
        GeoJSON file named:
        - inventory_<location>_nsi.geojson (for --location)
        - inventory_bbox_<coords>_nsi.geojson (for --bbox)
    
    Exit Codes:
        0: Success
        Non-zero: Error occurred during processing
    """
    parser = argparse.ArgumentParser(
        description="Get building inventory with NSI (YearBuilt etc.). Choose --location OR --bbox. No post-processing."
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--location", type=str, help='e.g., "Northridge, Los Angeles, CA"')
    group.add_argument("--bbox", nargs=4, type=float, metavar=("LON_MIN", "LAT_MIN", "LON_MAX", "LAT_MAX"),
                       help="Custom bbox in degrees")

    args = parser.parse_args()

    importer = Importer()

    # Fastest footprint source by default
    Scraper = importer.get_class("OSM_FootprintScraper")
    scraper = Scraper({"length": "ft"})  # length unit passed through; NSI also uses this

    # 1) Footprints
    inventory = fetch_footprints(importer, scraper, location=args.location, bbox=args.bbox)
    print(f"Footprints retrieved: {len(inventory.inventory)}")

    # 2) NSI merge (always on)
    inventory = chunked_merge_nsi(inventory, length_unit="ft", chunk_size=1500)
    print(f"After NSI merge: {len(inventory.inventory)} assets")

    # 3) Write output
    if args.location:
        safe = "".join(c for c in args.location if c.isalnum() or c in (" ", "_", "-")).strip().replace(" ", "_")
        out_path = Path(f"inventory_{safe}_nsi.geojson")
    else:
        lon_min, lat_min, lon_max, lat_max = args.bbox
        out_path = Path(f"inventory_bbox_{lon_min}_{lat_min}_{lon_max}_{lat_max}_nsi.geojson")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    inventory.write_to_geojson(str(out_path))
    print(f"✅ Wrote {len(inventory.inventory)} assets to: {out_path.resolve()}")

    # Small peek at keys
    try:
        some_key = next(iter(inventory.inventory.keys()))
        feat = inventory.inventory[some_key].features
        print("Sample keys:", list(feat.keys())[:20])
    except Exception:
        pass


if __name__ == "__main__":
    main()

