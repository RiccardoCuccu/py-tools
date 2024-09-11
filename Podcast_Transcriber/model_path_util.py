import os

def model_path(model_dir):
    # Get a list of all subdirectories (models) in the model base path
    model_paths = [d for d in os.listdir(model_dir) if os.path.isdir(os.path.join(model_dir, d))]

    if len(model_paths) == 0:
        raise Exception(f"No models found in {model_dir}. Please download a Vosk model from: https://alphacephei.com/vosk/models")
    
    elif len(model_paths) == 1:
        # If only one model is found, use it automatically
        model_path = os.path.join(model_dir, model_paths[0])
        return model_path
    
    else:
        # If multiple models are found, ask the user to select one
        print("Multiple models found. Please choose which model to use:")
        for i, model_name in enumerate(model_paths):
            print(f"{i + 1}. {model_name}")
        
        # Get user's choice
        while True:
            try:
                choice = int(input("Enter the number of the model to use: ")) - 1
                if 0 <= choice < len(model_paths):
                    selected_model = model_paths[choice]
                    model_path = os.path.join(model_dir, selected_model)
                    print(f"Using model: {selected_model}")
                    return model_path
                else:
                    print("Invalid selection. Please try again.")
            except ValueError:
                print("Invalid input. Please enter a number.")
