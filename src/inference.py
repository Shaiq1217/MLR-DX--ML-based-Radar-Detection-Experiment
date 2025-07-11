from torchvision import datasets, transforms
from torch.utils.data import DataLoader
import torch
import numpy as np
import os
import matplotlib.pyplot as plt
import seaborn as sns
import pandas as pd
from sklearn.metrics import classification_report, confusion_matrix, f1_score, precision_score, recall_score
import cv2


def get_test_loader(num_channels = 1, path="test"):
    """Get the test DataLoader."""
    # Define the transformation to apply to each image
    transform = transforms.Compose([
        transforms.Grayscale(num_output_channels=num_channels),  # Convert to grayscale   
        transforms.Resize((224, 224)),   
        transforms.ToTensor(),
        transforms.Normalize((0.5, ), (0.5,))
    ])

    test_dataset = datasets.ImageFolder(root=path, transform=transform)
    test_loader = DataLoader(test_dataset, batch_size=32, shuffle=False)

    classes = test_dataset.classes
    return test_loader, classes


def add_gaussian_noise(tensor, mean=0.0, std=0.1, multiplier=1.0):
    """Add Gaussian noise to a tensor image."""
    noise = torch.randn_like(tensor) * std * multiplier + mean
    return torch.clamp(tensor + noise, 0., 1.)

def run_inferece(model, device='cpu', num_channels=1, confusion_matrix_path="out/cnn_confusion_matrix.png", metrics_path = "out/metrics_noise_cnn.csv", noise_multiplier=0.0):
    """Run inference on the test dataset with optional Gaussian noise."""
    test_loader, classes = get_test_loader(num_channels)
    
    all_preds = []
    all_labels = []

    with torch.no_grad():
        for inputs, labels in test_loader:
            # Add Gaussian noise to inputs
            if noise_multiplier > 0:
                inputs = add_gaussian_noise(inputs, std=0.1, multiplier=noise_multiplier)

            inputs = inputs.to(device)
            labels = labels.to(device)

            outputs = model(inputs)
            _, preds = torch.max(outputs, 1)

            all_preds.extend(preds.cpu().numpy())
            all_labels.extend(labels.cpu().numpy())

    # Evaluation metrics
    report = classification_report(all_labels, all_preds, target_names=classes)
    cm = confusion_matrix(all_labels, all_preds)
    f1 = f1_score(all_labels, all_preds, average='weighted')
    precision = precision_score(all_labels, all_preds, average='weighted')
    recall = recall_score(all_labels, all_preds, average='weighted')

    # Print metrics
    print("Classification Report:\n", report)
    print("\nConfusion Matrix:\n", cm)
    print(f"\nF1 Score: {f1:.4f}")
    print(f"Precision: {precision:.4f}")
    print(f"Recall: {recall:.4f}")

    # Write metrics to a csv file with noise multiplier
    metrics = {
        "Noise Multiplier": [noise_multiplier],
        "F1 Score": [f1],
        "Precision": [precision],
        "Recall": [recall]
    }
    metrics_df = pd.DataFrame(metrics)
    metrics_df.to_csv(metrics_path, index=False, mode='a', header=not os.path.exists(metrics_path))

    # Plot and save confusion matrix
    plt.figure(figsize=(8, 6))
    cm_df = pd.DataFrame(cm, index=classes, columns=classes)
    sns.heatmap(cm_df, annot=True, fmt='d', cmap='Blues', cbar=False)
    plt.title(f"Confusion Matrix (Noise Multiplier: {noise_multiplier})")
    plt.ylabel("Actual")
    plt.xlabel("Predicted")
    plt.tight_layout()
    plt.savefig(confusion_matrix_path)
    plt.close()

def run_gradcam(
    model, device='cpu', num_channels=1,
    test_loader = None, classes = None,
    gradcam_output_dir="out/gradcam/",
    noise_multiplier=0.0,
):
    os.makedirs(gradcam_output_dir, exist_ok=True)

    all_preds = []
    all_labels = []

    # Hook to store gradients and activations
    gradients = []
    activations = []

    def save_gradient(module, grad_input, grad_output):
        gradients.append(grad_output[0])

    def save_activation(module, input, output):
        activations.append(output)

    # Register hooks on the last conv layer
    target_layer = list(model.modules())[-5]  # Adjust based on your model
    target_layer.register_forward_hook(save_activation)
    target_layer.register_full_backward_hook(save_gradient)

    model.eval()

    sample_idx = 0  # to uniquely name each saved Grad-CAM

    for inputs, labels in test_loader:
        if noise_multiplier > 0:
            inputs = add_gaussian_noise(inputs, std=0.1, multiplier=noise_multiplier)

        inputs = inputs.to(device)
        labels = labels.to(device)

        outputs = model(inputs)
        _, preds = torch.max(outputs, 1)

        for i in range(len(inputs)):
            model.zero_grad()


            class_score = outputs[i, preds[i]]
            class_score.backward(retain_graph=True)

            # Grad-CAM calculation
            pooled_grad = torch.mean(gradients[-1][i], dim=(1, 2))
            activation = activations[-1][i]

            for j in range(len(pooled_grad)):
                activation[j, :, :] *= pooled_grad[j]

            heatmap = torch.mean(activation, dim=0).cpu().detach().numpy()
            heatmap = np.maximum(heatmap, 0)
            heatmap /= (heatmap.max() + 1e-8)


            heatmap_resized = cv2.resize(heatmap, (224, 224))
            heatmap_rgb = cv2.applyColorMap(np.uint8(255 * heatmap_resized), cv2.COLORMAP_JET)
            cv2.imwrite(
                os.path.join(
                    gradcam_output_dir,
                    f"gradcam_sample_{sample_idx}_class_{classes[preds[i]]}.png"
                ),
                heatmap_rgb
            )
            sample_idx += 1
         
