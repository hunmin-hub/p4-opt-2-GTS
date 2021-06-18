'''
pip install tensorflow
pip install pytorch2keras
pip install tflite-support-nightly
'''
import torch
import torch.nn as nn
import tensorflow as tf
from torch.autograd import Variable
from pytorch2keras.converter import pytorch_to_keras

from tflite_support.metadata_writers import image_classifier
from tflite_support.metadata_writers import writer_utils
from tflite_support import metadata

import numpy as np
import yaml
from typing import Any, Dict, List, Optional, Tuple, Union
import random
import os
from src.model import Model
from src.utils.torch_utils import *
from src.utils.train_utils import *
from src.utils.common import *
import argparse
import warnings
import logging

def get_nas_model(cfg, activation_func):
    model_config = read_yaml(cfg=cfg)
    model_instance = Model(model_config, verbose=False)
    net = model_instance.model
    # Select activation function
    if activation_func == "softmax":
        net[-1].activation = nn.Softmax(dim=1)
    else:
        net[-1].activation = nn.Sigmoid()
    print(net)
    net.eval()
    return net

class Torch2tflite:
    def __init__(self, model_cfg, activation_func, model_path, label_path, save_path, model_name, image_size = 224):
        self.activation_func = activation_func
        self.pytorch_model = get_nas_model(model_cfg, self.activation_func)
        self.pytorch_model.state_dict(torch.load(model_path))
        self.save_path = save_path
        self.label_path = label_path
        self.image_size = image_size
        self.model_name = model_name


    def convert(self):
        self.__torch2keras()
        self.__keras2tflite()
        self.__tfliteInferenceTest()
        self.__tfliteMetadata()

    def __torch2keras(self):
        print("[Info] torch2keras...", end="")
        
        input_np = np.random.uniform(0, 1, (1, 3, self.image_size, self.image_size))
        input_var = Variable(torch.FloatTensor(input_np))

        self.k_model = pytorch_to_keras(self.pytorch_model, input_var, [(3, self.image_size, self.image_size,)], verbose=False, change_ordering=True)
        print(self.k_model.summary())
        print("Done...")

    def __keras2tflite(self):
        converter = tf.lite.TFLiteConverter.from_keras_model(self.k_model)
        self.tflite_model = converter.convert()
        
        self.__tflite_path = os.path.join(self.save_path, self.model_name + ".tflite")
        open(self.__tflite_path, 'wb').write(self.tflite_model)
    
    def __tfliteInferenceTest(self):
        interpreter = tf.lite.Interpreter(model_path=self.__tflite_path)
        interpreter.allocate_tensors()
        input_index = interpreter.get_input_details()[0]['index']
        output_index = interpreter.get_output_details()[0]['index']
        temp_input = tf.random.uniform((1, self.image_size, self.image_size, 3))
        interpreter.set_tensor(input_index,temp_input)
        interpreter.invoke()
        print(interpreter.get_tensor(output_index))
    
    def __tfliteMetadata(self):
        ImageClassifierWriter = image_classifier.MetadataWriter

        # Standard : Imagenet
        _INPUT_NORM_MEAN = 127.5
        _INPUT_NORM_STD = 127.5

        # Create the metadata writer.
        writer = ImageClassifierWriter.create_for_inference(
            writer_utils.load_file(self.__tflite_path), [_INPUT_NORM_MEAN], [_INPUT_NORM_STD], [self.label_path])

        # Verify the metadata generated by metadata writer.
        print(writer.get_metadata_json())

        # Populate the metadata into the model.
        writer_utils.save_file(writer.populate(), self.__tflite_path)

    @property
    def tflite_path(self):
        return self.__tflite_path


if __name__=="__main__":
    warnings.filterwarnings(action='ignore')
    tf.get_logger().setLevel(3)
    parser = argparse.ArgumentParser()
    parser.add_argument("--model_cfg", type=str, default="./configs/model/GTSNet_Mask.yaml", help="set model config file path")
    parser.add_argument("--model_path", type=str, default="./pytorch_model/gtsnet_mask.pth", help="set saved model weight file path")
    parser.add_argument("--label_path", type=str, default="./pytorch_model/label.txt", help="set label list on txt file")
    parser.add_argument("--activation_func", type=str, default="softmax", help="your model inference activation function. ex) softmax or sigmoid")

    parser.add_argument("--save_path", type=str, default="./converted_model", help="set save path for converted model") 
    
    parser.add_argument("--image_size", type=int, default=224, help="set image size")
    parser.add_argument("--model_name", type=str, default="convert_model", help="set converted model name ex) [model_name].tflite")

    args = parser.parse_args()

    tflite_converter = Torch2tflite(model_cfg= args.model_cfg,
                                    activation_func= args.activation_func,
                                    model_path= args.model_path,
                                    label_path= args.label_path,
                                    save_path= args.save_path,
                                    model_name= args.model_name,
                                    image_size= args.image_size)
    
    tflite_converter.convert()

    print("Process..Done")
    print("TensorFlow Lite Convert Model saved path: \t\t", tflite_converter.tflite_path)