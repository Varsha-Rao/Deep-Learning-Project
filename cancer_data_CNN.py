# -*- coding: utf-8 -*-
"""cancer-data

Automatically generated by Colaboratory.

Original file is located at
    https://colab.research.google.com/drive/1uCaMB2zFoPdyjgzdXG2G5HwPAURTgerh
"""

import numpy as np 
import pandas as pd 
import matplotlib.pyplot as plt
import os
import random
import cv2
import tensorflow as tf
from glob import glob
from random import shuffle

from keras import layers
from keras.models import Model, load_model
from keras.utils.np_utils import to_categorical
from keras.layers import Input, Add, Dense, Activation, ZeroPadding2D, BatchNormalization, Flatten, Conv2D, AveragePooling2D, MaxPooling2D, GlobalMaxPooling2D
from keras.models import Model, load_model
from keras.losses import  binary_crossentropy
from keras.optimizers import Adam
from keras.preprocessing import image
from keras.callbacks import EarlyStopping, ModelCheckpoint
from keras.initializers import glorot_uniform
from keras import backend as K
from sklearn.model_selection import train_test_split
from sklearn import metrics

# Parameters
learning_rate = 1e-4
epochs = 5
batch_size = 32
test_size = 0.20
seed = 100000

np.random.seed(seed)

#For augmentation
ORIGINAL_SIZE = 96      
CROP_SIZE = 64          
RANDOM_ROTATION = 180   
RANDOM_SHIFT = 4        
RANDOM_BRIGHTNESS = 10   
RANDOM_CONTRAST = 10     


# Load data
df_train = pd.read_csv("/kaggle/input/histopathologic-cancer-detection/train_labels.csv")
id_label_map = {i:j for i,j in zip(df_train.id.values, df_train.label.values)}

def get_id(path):
    return path.split(os.path.sep)[-1].replace('.tif', '')
    
train_files = glob('/kaggle/input/histopathologic-cancer-detection/train/*.tif')
test_files = glob('/kaggle/input/histopathologic-cancer-detection/test/*.tif')
train, val = train_test_split(train_files, test_size=test_size, random_state=seed)

def readImage(path,augment):
    img = cv2.imread(path)
    #Convert to rgb
    b,g,r = cv2.split(img)
    rgb_img = cv2.merge([r,g,b])
    x = 0
    y = 0
    #Data augmentation
    if augment:
        rotation = random.randint(-RANDOM_ROTATION,RANDOM_ROTATION)  
        M = cv2.getRotationMatrix2D((48,48),rotation,1)
        rgb_img = cv2.warpAffine(rgb_img,M,(96,96))
        
        x = random.randint(-RANDOM_SHIFT, RANDOM_SHIFT)
        y = random.randint(-RANDOM_SHIFT, RANDOM_SHIFT)

        flip_hor = bool(random.getrandbits(1))
        flip_ver = bool(random.getrandbits(1))
        if(flip_hor):
            rgb_img = rgb_img[:, ::-1]
        if(flip_ver):
            rgb_img = rgb_img[::-1, :]
        br = random.randint(-RANDOM_BRIGHTNESS, RANDOM_BRIGHTNESS) / 100.
        rgb_img = rgb_img + br
        cr = 1.0 + random.randint(-RANDOM_CONTRAST, RANDOM_CONTRAST) / 100.
        rgb_img = rgb_img * cr
    
    start_crop = (ORIGINAL_SIZE - CROP_SIZE) // 2
    end_crop = start_crop + CROP_SIZE
    rgb_img = rgb_img[(start_crop + x):(end_crop + x), (start_crop + y):(end_crop + y)] / 255
    
    rgb_img = np.clip(rgb_img, 0, 1.0) #between 0 and 1
    return rgb_img

def chunker(seq, size):
    return (seq[pos:pos + size] for pos in range(0, len(seq), size))

def data_gen(list_files, id_label_map, batch_size, augment=False):
    while True:
        shuffle(list_files)
        for batch in chunker(list_files, batch_size):
            X = [readImage(x,augment) for x in batch]
            Y = [id_label_map[get_id(x)] for x in batch]
            yield np.array(X), np.array(Y)
            
def identity_block(X, f, filters, stage, block):

    conv = 'res' + str(stage) + block + '_branch'
    bn = 'bn' + str(stage) + block + '_branch'
    
    F1, F2, F3 = filters
    X_shortcut = X
    X = Conv2D(filters = F1, kernel_size = (1, 1), strides = (1,1), padding = 'valid', name = conv + '2a')(X)
    X = BatchNormalization(axis = 3, name = bn + '2a')(X)
    X = Activation('relu')(X)
    X = Conv2D(filters = F2, kernel_size = (f, f), strides = (1,1), padding = 'same', name = conv + '2b')(X)
    X = BatchNormalization(axis = 3, name = bn + '2b')(X)
    X = Activation('relu')(X)
    X = Conv2D(filters = F3, kernel_size = (1, 1), strides = (1,1), padding = 'valid', name = conv + '2c')(X)
    X = BatchNormalization(axis = 3, name = bn + '2c')(X)
    X = layers.Add()([X,X_shortcut])
    X = Activation('relu')(X)
    
    return X
    
def convolutional_block(X, f, filters, stage, block, s = 2):
    
    conv = 'res' + str(stage) + block + '_branch'
    bn = 'bn' + str(stage) + block + '_branch'
    
    F1, F2, F3 = filters
    X_shortcut = X
    X = Conv2D(F1, (1, 1), strides = (s,s), name = conv + '2a')(X)
    X = BatchNormalization(axis = 3, name = bn + '2a')(X)
    X = Activation('relu')(X)
    X = Conv2D(filters = F2, kernel_size = (f, f), strides = (1,1), padding = 'same', name = conv + '2b')(X)
    X = BatchNormalization(axis = 3, name = bn + '2b')(X)
    X = Activation('relu')(X)
    X = Conv2D(filters = F3, kernel_size = (1, 1), strides = (1,1), padding = 'valid', name = conv + '2c')(X)
    X = BatchNormalization(axis = 3, name = bn + '2c')(X)
    X_shortcut = Conv2D(filters = F3, kernel_size = (1, 1), strides = (s,s), padding = 'same', name = conv + '1')(X_shortcut)
    X_shortcut = BatchNormalization(axis = 3, name = bn + '1')(X_shortcut)
    X = layers.Add()([X,X_shortcut])
    X = Activation('relu')(X)
    
    return X



def ResNet50_model(input_shape = (CROP_SIZE, CROP_SIZE, 3), classes = 1):
    inputs = Input(input_shape)

    X_input = Input(input_shape)
    X = ZeroPadding2D((3, 3))(X_input)
    X = Conv2D(64, (7, 7), strides = (2, 2), name = 'conv1')(X)
    X = BatchNormalization(axis = 3, name = 'bn_conv1')(X)
    X = Activation('relu')(X)
    X = MaxPooling2D((3, 3), strides=(2, 2))(X)
    X = convolutional_block(X, f = 3, filters = [64, 64, 256], stage = 2, block='a', s = 1)
    X = identity_block(X, 3, [64, 64, 256], stage=2, block='b')
    X = identity_block(X, 3, [64, 64, 256], stage=2, block='c')
    X = convolutional_block(X, f = 3, filters = [128,128,512], stage = 3, block='a', s = 2)
    X = identity_block(X, 3, [128,128,512], stage = 3, block='b')
    X = identity_block(X, 3, [128,128,512], stage = 3, block='c')
    X = identity_block(X, 3, [128,128,512], stage = 3, block='d')
    X = convolutional_block(X, f = 3, filters = [256,256,1024], stage = 4, block='a', s = 2)
    X = identity_block(X, 3, [256,256,1024], stage = 4, block='b')
    X = identity_block(X, 3, [256,256,1024], stage = 4, block='c')
    X = identity_block(X, 3, [256,256,1024], stage = 4, block='d')
    X = identity_block(X, 3, [256,256,1024], stage = 4, block='e')
    X = identity_block(X, 3, [256,256,1024], stage = 4, block='f')
    X = convolutional_block(X, f = 3, filters = [512,512,2048], stage = 5, block='a', s = 2)
    X = identity_block(X, 3, [512,512,2048], stage = 5, block='b')
    X = identity_block(X, 3, [512,512,2048], stage = 5, block='c')
    X = AveragePooling2D(pool_size=(2, 2), name = 'avg_pool')(X)
    X = Flatten()(X)
    X = Dense(classes, activation='sigmoid', name='fc' + str(classes), kernel_initializer = glorot_uniform(seed=0))(X)
    
    
    # Create model
    model = Model(inputs = X_input, outputs = X, name='ResNet50')
    model.compile(Adam(learning_rate), loss=binary_crossentropy)
    
    return model

model = ResNet50_model()


h5_path = "model.res50"
checkpoint = ModelCheckpoint(h5_path, monitor='val_auc', verbose=1, save_best_only=True, mode='max')
earlystopper = EarlyStopping(monitor='auc', patience=5, verbose=1)

    
history = model.fit_generator(
    data_gen(train, id_label_map, batch_size, augment=False),
    validation_data=data_gen(val, id_label_map, batch_size),
    epochs=epochs, verbose=1,
    callbacks=[checkpoint,earlystopper],
    steps_per_epoch=len(train) // batch_size,
    validation_steps=len(val) // batch_size)

model.load_weights(h5_path)

preds = []
ids = []
for batch in chunker(test_files, batch_size):
    X = [readImage(x,False) for x in batch]
    ids_batch = [get_id(x) for x in batch]
    X = np.array(X)
    preds_batch = ((model.predict(X).ravel()*model.predict(X[:, ::-1, :, :]).ravel()*model.predict(X[:, ::-1, ::-1, :]).ravel()*model.predict(X[:, :, ::-1, :]).ravel())**0.25).tolist()
    preds += preds_batch
    ids += ids_batch
df = pd.DataFrame({'id':ids, 'label':preds})
df.to_csv("submit.csv", index=False)
df.head()