# CS229 Earthquake Repair Cost Prediction - Code Usage Guide

This repository contains the code for the CS229 project: **Predicting Earthquake-Induced Repair Costs using Machine Learning**. This guide explains the structure of the codebase and how to use the provided scripts and notebooks to reproduce the results.

## Project Structure

*   **`get_inventory_simple.py`**: A CLI script to fetch building footprints (from OpenStreetMap or USA Footprint database) and merge them with National Structure Inventory (NSI) data to create a rich building inventory.
*   **`PBETool.ipynb` / `PBETool_LOCAL.ipynb`**: Jupyter notebooks for running the physics-based PBE (Performance-Based Engineering) simulations. These simulations generate the "ground truth" loss ratios used for training.
*   **`subset_creation.ipynb`**: Handles data preprocessing and splits the dataset into training, validation, and testing sets.
*   **`Models.ipynb`**: Implements and trains the Supervised Learning models (Baseline MLP and Regularized MLP) using Keras/TensorFlow.
*   **`Semisupervised Gaussian Mixture Model.ipynb`**: Implements the Semi-Supervised Gaussian Mixture Model (GMM) approach.
*   **`BuildingGenerator.ipynb`**: Notebook for generating synthetic or processing existing building data.
*   **`scInput - template.json`**: Template input file for the PBE simulation tool.

## Prerequisites

### Python Dependencies
Ensure you have the following Python libraries installed:
```bash
pip install pandas numpy matplotlib seaborn scikit-learn tensorflow keras
```
For the inventory generator, you also need `BrailsPlusPlus`:
```bash
pip install --upgrade git+https://github.com/NHERI-SimCenter/BrailsPlusPlus
```

### External Software
*   **SimCenter PBE Application**: The `PBETool.ipynb` notebooks require a local installation of the NHERI SimCenter PBE Application to run the physics-based simulations.

## Usage Instructions

### 1. Generating Building Inventory
Use `get_inventory_simple.py` to create a dataset of buildings for a specific region.

**By Location Name:**
```bash
python get_inventory_simple.py --location "Northridge, Los Angeles, CA"
```

**By Bounding Box (Long/Lat):**
```bash
python get_inventory_simple.py --bbox -118.5 34.2 -118.4 34.3
```
This will output a GeoJSON file (e.g., `inventory_Northridge_nsi.geojson`) containing building attributes.

### 2. Running PBE Simulations (Data Generation)
To generate the training labels (Loss Ratios):
1.  Open `PBETool.ipynb` or `PBETool_LOCAL.ipynb`.
2.  Update the paths to point to your local PBE Application installation (`PYTHON_EXE`, `PBE_WORKFLOW_SCRIPT`, etc.).
3.  Configure the `JSON_INPUT_FILE` path.
4.  Run the notebook to execute the batch simulations. This process can be time-consuming (~30s per building).

### 3. Data Preprocessing
Before training, the raw simulation data needs to be processed and split:
1.  Open `subset_creation.ipynb`.
2.  **Important**: Update the file paths (e.g., `base_dir`) to point to your local data directory. The current notebooks may reference shared drive paths (e.g., `G:/Shared drives/...`).
3.  Run the cells to generate the pickled dataset files: `X_train.pkl`, `y_train.pkl`, `X_validation.pkl`, etc.

### 4. Training Models

#### Supervised Learning (MLP)
1.  Open `Models.ipynb`.
2.  Update the `dir` variable to point to the folder containing your pickled dataset files.
3.  Run the notebook to:
    *   Load the data.
    *   Train the Baseline MLP.
    *   Train the Regularized MLP (with L2 weight decay and Batch Normalization).
    *   Evaluate performance (MSE, MAE).

#### Semi-Supervised Learning (GMM)
1.  Open `Semisupervised Gaussian Mixture Model.ipynb`.
2.  Update the data paths (note: this notebook may currently reference Google Drive paths like `/content/drive/...`).
3.  Run the notebook to train the GMM using both labeled and unlabeled data.

## Note on File Paths
Many notebooks currently contain hardcoded absolute paths (e.g., `G:/Shared drives/CS229 Project/...` or `/content/drive/...`). **You must update these paths** to match your local directory structure before running the code.
