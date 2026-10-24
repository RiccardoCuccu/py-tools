#!/usr/bin/env python3
"""
model_path_util.py - Locate and select a Vosk model directory from the models folder.
"""

import os

MODELS_URL = "https://alphacephei.com/vosk/models"


def list_model_names(model_dir):
    """Return the sorted names of the model sub-directories in model_dir."""
    if not os.path.isdir(model_dir):
        raise FileNotFoundError(
            f"Models folder {model_dir} does not exist. "
            f"Create it and place a Vosk model from {MODELS_URL} inside."
        )

    return sorted(d for d in os.listdir(model_dir) if os.path.isdir(os.path.join(model_dir, d)))


def model_path(model_dir):
    """Return the path to the Vosk model to use, prompting the user if multiple are present."""
    model_names = list_model_names(model_dir)

    if len(model_names) == 0:
        raise FileNotFoundError(
            f"No models found in {model_dir}. Please download a Vosk model from: {MODELS_URL}"
        )

    if len(model_names) == 1:
        return os.path.join(model_dir, model_names[0])

    print("Multiple models found. Please choose which model to use:")
    for i, model_name in enumerate(model_names):
        print(f"{i + 1}. {model_name}")

    while True:
        try:
            choice = int(input("Enter the number of the model to use: ")) - 1
        except ValueError:
            print("Invalid input. Please enter a number.")
            continue

        if 0 <= choice < len(model_names):
            selected_model = model_names[choice]
            print(f"Using model: {selected_model}")
            return os.path.join(model_dir, selected_model)

        print("Invalid selection. Please try again.")
