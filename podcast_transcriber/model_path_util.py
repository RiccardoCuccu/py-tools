#!/usr/bin/env python3
"""
model_path_util.py - Locate and select a Vosk model directory from the models folder.
"""

import os


def model_path(model_dir):
    """Return the path to the Vosk model to use, prompting the user if multiple are present."""
    model_paths = [d for d in os.listdir(model_dir) if os.path.isdir(os.path.join(model_dir, d))]

    if len(model_paths) == 0:
        raise Exception(
            f"No models found in {model_dir}. "
            "Please download a Vosk model from: https://alphacephei.com/vosk/models"
        )

    if len(model_paths) == 1:
        return os.path.join(model_dir, model_paths[0])

    print("Multiple models found. Please choose which model to use:")
    for i, model_name in enumerate(model_paths):
        print(f"{i + 1}. {model_name}")

    while True:
        try:
            choice = int(input("Enter the number of the model to use: ")) - 1
            if 0 <= choice < len(model_paths):
                selected_model = model_paths[choice]
                print(f"Using model: {selected_model}")
                return os.path.join(model_dir, selected_model)
            else:
                print("Invalid selection. Please try again.")
        except ValueError:
            print("Invalid input. Please enter a number.")
