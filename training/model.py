import torch
import torch.nn.functional as F
from torch import nn


class CNN(nn.Module):
    def __init__(self, num_classes: int, image_size: int) -> None:
        """
        Define the layers of the convolutional neural network.

        :param num_classes: The number of classes we want to predict, in our case 10 (digits 0 to 9).
        :param image_size: The size of the input image.
        """
        super(CNN, self).__init__()

        self.image_size = image_size

        # Image size is cut in half with each pooling.
        # This makes the fully connected layer have x * image_size/8 * image_size/8 input features.
        self.conv1 = nn.Conv2d(1, 8, kernel_size=3, padding=1)
        self.bn1 = nn.BatchNorm2d(8)

        self.conv2 = nn.Conv2d(8, 16, kernel_size=3, padding=1)
        self.bn2 = nn.BatchNorm2d(16)
        self.pool1 = nn.MaxPool2d(2, 2)

        self.conv3 = nn.Conv2d(16, 32, kernel_size=3, padding=1)
        self.bn3 = nn.BatchNorm2d(32)

        self.conv4 = nn.Conv2d(32, 64, kernel_size=3, padding=1)
        self.bn4 = nn.BatchNorm2d(64)
        self.pool2 = nn.MaxPool2d(2, 2)

        # self.conv5 = nn.Conv2d(128, 256, kernel_size=3, padding=1)
        # self.bn5 = nn.BatchNorm2d(256)
        # self.pool3 = nn.MaxPool2d(2, 2)

        self.fc1 = nn.Linear(64 * image_size // 4 * image_size // 4, 2048)
        self.dropout = nn.Dropout(0.6)
        self.fc2 = nn.Linear(2048, num_classes)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """
        Define the forward pass of the neural network.

        :param x: The input tensor.
        :return: The output tensor after passing through the network.
        """
        x = F.relu(self.bn1(self.conv1(x)))
        x = F.relu(self.bn2(self.conv2(x)))
        x = self.pool1(x)
        x = F.relu(self.bn3(self.conv3(x)))
        x = F.relu(self.bn4(self.conv4(x)))
        x = self.pool2(x)
        # x = F.relu(self.bn5(self.conv5(x)))
        # x = self.pool3(x)
        x = x.view(-1, 64 * self.image_size // 4 * self.image_size // 4)
        x = F.relu(self.fc1(x))
        x = self.dropout(x)
        x = self.fc2(x)
        return x
