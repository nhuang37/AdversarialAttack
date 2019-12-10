import json
import os
import time
from abc import ABC

import numpy as np
from sklearn.model_selection import train_test_split

from astroNN.config import MULTIPROCESS_FLAG
from astroNN.config import _astroNN_MODEL_NAME
from astroNN.config import keras_import_manager
from astroNN.models.base_master_nn import NeuralNetMaster
from astroNN.nn.callbacks import VirutalCSVLogger
from astroNN.nn.losses import categorical_crossentropy, binary_crossentropy
from astroNN.nn.losses import mean_squared_error, mean_absolute_error, mean_error
from astroNN.nn.metrics import categorical_accuracy, binary_accuracy
from astroNN.nn.utilities import Normalizer
from astroNN.nn.utilities.generator import GeneratorMaster

#keras = keras_import_manager()
import keras
regularizers = keras.regularizers
ReduceLROnPlateau, EarlyStopping = keras.callbacks.ReduceLROnPlateau, keras.callbacks.EarlyStopping
Adam = keras.optimizers.Adam


class CNNDataGenerator(GeneratorMaster):
    """
    To generate data to NN

    :param batch_size: batch size
    :type batch_size: int
    :param shuffle: Whether to shuffle batches or not
    :type shuffle: bool
    :param data: List of data to NN
    :type data: list
    :History:
        | 2017-Dec-02 - Written - Henry Leung (University of Toronto)
        | 2019-Feb-17 - Updated - Henry Leung (University of Toronto)
    """

    def __init__(self, batch_size, shuffle, steps_per_epoch, data):
        super().__init__(batch_size=batch_size, shuffle=shuffle, steps_per_epoch=steps_per_epoch, data=data)
        self.inputs = self.data[0]
        self.labels = self.data[1]

        # initial idx
        self.idx_list = self._get_exploration_order(range(self.inputs.shape[0]))
        self.current_idx = 0

    def _data_generation(self, inputs, labels, idx_list_temp):
        x = self.input_d_checking(inputs, idx_list_temp)
        y = labels[idx_list_temp]
        return x, y

    def __getitem__(self, index):
        x, y = self._data_generation(self.inputs,
                                     self.labels,
                                     self.idx_list[self.current_idx:self.current_idx + self.batch_size])
        self.current_idx += self.batch_size
        return x, y

    def on_epoch_end(self):
        # shuffle the list when epoch ends for the next epoch
        self.idx_list = self._get_exploration_order(range(self.inputs.shape[0]))
        # reset counter
        self.current_idx = 0


class CNNPredDataGenerator(GeneratorMaster):
    """
    To generate data to NN for prediction

    :param batch_size: batch size
    :type batch_size: int
    :param shuffle: Whether to shuffle batches or not
    :type shuffle: bool
    :param data: List of data to NN
    :type data: list
    :History:
        | 2017-Dec-02 - Written - Henry Leung (University of Toronto)
        | 2019-Feb-17 - Updated - Henry Leung (University of Toronto)
    """

    def __init__(self, batch_size, shuffle, steps_per_epoch, data):
        super().__init__(batch_size=batch_size, shuffle=shuffle, steps_per_epoch=steps_per_epoch, data=data)
        self.inputs = self.data[0]

        # initial idx
        self.idx_list = self._get_exploration_order(range(self.inputs.shape[0]))
        self.current_idx = 0

    def _data_generation(self, inputs, idx_list_temp):
        # Generate data
        x = self.input_d_checking(inputs, idx_list_temp)
        return x

    def __getitem__(self, index):
        x = self._data_generation(self.inputs, self.idx_list[self.current_idx:self.current_idx + self.batch_size])
        self.current_idx += self.batch_size
        return x

    def on_epoch_end(self):
        # shuffle the list when epoch ends for the next epoch
        self.idx_list = self._get_exploration_order(range(self.inputs.shape[0]))
        # reset counter
        self.current_idx = 0


class CNNBase(NeuralNetMaster, ABC):
    """Top-level class for a convolutional neural network"""

    def __init__(self):
        """
        NAME:
            __init__
        PURPOSE:
            To define astroNN convolutional neural network
        HISTORY:
            2018-Jan-06 - Written - Henry Leung (University of Toronto)
        """
        super().__init__()
        self.name = 'Convolutional Neural Network'
        self._model_type = 'CNN'
        self._model_identifier = None
        self.initializer = None
        self.activation = None
        self._last_layer_activation = None
        self.num_filters = None
        self.filter_len = None
        self.pool_length = None
        self.num_hidden = None
        self.reduce_lr_epsilon = None
        self.reduce_lr_min = None
        self.reduce_lr_patience = None
        self.l1 = None
        self.l2 = None
        self.maxnorm = None
        self.dropout_rate = 0.0
        self.val_size = 0.1
        self.early_stopping_min_delta = 0.0001
        self.early_stopping_patience = 4

        self.input_norm_mode = 1
        self.labels_norm_mode = 2

    def compile(self, optimizer=None, loss=None, metrics=None, loss_weights=None, sample_weight_mode=None):
        if optimizer is not None:
            self.optimizer = optimizer
        elif self.optimizer is None or self.optimizer == 'adam':
            self.optimizer = Adam(lr=self.lr, beta_1=self.beta_1, beta_2=self.beta_2, epsilon=self.optimizer_epsilon,
                                  decay=0.0)

        if self.task == 'regression':
            self._last_layer_activation = 'linear'
            loss_func = mean_squared_error
            if self.metrics is None:
                self.metrics = [mean_absolute_error, mean_error]
        elif self.task == 'classification':
            self._last_layer_activation = 'softmax'
            loss_func = categorical_crossentropy
            if self.metrics is None:
                self.metrics = [categorical_accuracy]
        elif self.task == 'binary_classification':
            self._last_layer_activation = 'sigmoid'
            loss_func = binary_crossentropy
            if self.metrics is None:
                self.metrics = [binary_accuracy(from_logits=False)]
        else:
            raise RuntimeError('Only "regression", "classification" and "binary_classification" are supported')

        self.keras_model = self.model()

        self.keras_model.compile(loss=loss_func, optimizer=self.optimizer, metrics=self.metrics, loss_weights=None)

        return None

    def pre_training_checklist_child(self, input_data, labels):
        self.pre_training_checklist_master(input_data, labels)

        # check if exists (exists mean fine-tuning, so we do not need calculate mean/std again)
        if self.input_normalizer is None:
            self.input_normalizer = Normalizer(mode=self.input_norm_mode)
            self.labels_normalizer = Normalizer(mode=self.labels_norm_mode)

            norm_data = self.input_normalizer.normalize(input_data)
            self.input_mean, self.input_std = self.input_normalizer.mean_labels, self.input_normalizer.std_labels
            norm_labels = self.labels_normalizer.normalize(labels)
            self.labels_mean, self.labels_std = self.labels_normalizer.mean_labels, self.labels_normalizer.std_labels
        else:
            norm_data = self.input_normalizer.normalize(input_data, calc=False)
            norm_labels = self.labels_normalizer.normalize(labels, calc=False)

        if self.keras_model is None:  # only compiler if there is no keras_model, e.g. fine-tuning does not required
            self.compile()

        self.train_idx, self.val_idx = train_test_split(np.arange(self.num_train + self.val_num),
                                                        test_size=self.val_size)

        self.training_generator = CNNDataGenerator(
            batch_size=self.batch_size,
            shuffle=True,
            steps_per_epoch=self.num_train // self.batch_size,
            data=[norm_data[self.train_idx], norm_labels[self.train_idx]])
        self.validation_generator = CNNDataGenerator(
            batch_size=self.batch_size if len(self.val_idx) > self.batch_size else len(self.val_idx),
            shuffle=False,
            steps_per_epoch=max(self.val_num // self.batch_size, 1),
            data=[norm_data[self.val_idx], norm_labels[self.val_idx]])

        return input_data, labels

    def train(self, input_data, labels):
        """
        Train a Convolutional neural network

        :param input_data: Data to be trained with neural network
        :type input_data: ndarray
        :param labels: Labels to be trained with neural network
        :type labels: ndarray
        :return: None
        :rtype: NoneType
        :History: 2017-Dec-06 - Written - Henry Leung (University of Toronto)
        """
        # Call the checklist to create astroNN folder and save parameters
        self.pre_training_checklist_child(input_data, labels)

        reduce_lr = ReduceLROnPlateau(monitor='val_mean_absolute_error', factor=0.5,
                                      #min_delta=self.reduce_lr_epsilon, 
                                      patience=self.reduce_lr_patience, min_lr=self.reduce_lr_min, mode='min',
                                      verbose=2)

        early_stopping = EarlyStopping(monitor='val_mean_absolute_error', min_delta=self.early_stopping_min_delta,
                                       patience=self.early_stopping_patience, verbose=2, mode='min')

        self.virtual_cvslogger = VirutalCSVLogger()

        self.__callbacks = [reduce_lr, self.virtual_cvslogger]  # default must have unchangeable callbacks

        if self.callbacks is not None:
            if isinstance(self.callbacks, list):
                self.__callbacks.extend(self.callbacks)
            else:
                self.__callbacks.append(self.callbacks)

        start_time = time.time()

        self.history = self.keras_model.fit_generator(generator=self.training_generator,
                                                      validation_data=self.validation_generator,
                                                      epochs=self.max_epochs, verbose=self.verbose,
                                                      workers=os.cpu_count(),
                                                      callbacks=self.__callbacks,
                                                      use_multiprocessing=MULTIPROCESS_FLAG)

        print(f'Completed Training, {(time.time() - start_time):.{2}f}s in total')

        if self.autosave is True:
            # Call the post training checklist to save parameters
            self.save()

        return None

    def train_on_batch(self, input_data, labels):
        """
        Train a neural network by running a single gradient update on all of your data, suitable for fine-tuning

        :param input_data: Data to be trained with neural network
        :type input_data: ndarray
        :param labels: Labels to be trained with neural network
        :type labels: ndarray
        :return: None
        :rtype: NoneType
        :History: 2018-Aug-22 - Written - Henry Leung (University of Toronto)
        """
        self.has_model_check()
        # check if exists (exists mean fine-tuning, so we do not need calculate mean/std again)
        if self.input_normalizer is None:
            self.input_normalizer = Normalizer(mode=self.input_norm_mode)
            self.labels_normalizer = Normalizer(mode=self.labels_norm_mode)

            norm_data = self.input_normalizer.normalize(input_data)
            self.input_mean, self.input_std = self.input_normalizer.mean_labels, self.input_normalizer.std_labels
            norm_labels = self.labels_normalizer.normalize(labels)
            self.labels_mean, self.labels_std = self.labels_normalizer.mean_labels, self.labels_normalizer.std_labels
        else:
            norm_data = self.input_normalizer.normalize(input_data, calc=False)
            norm_labels = self.labels_normalizer.normalize(labels, calc=False)

        start_time = time.time()

        fit_generator = CNNDataGenerator(batch_size=input_data.shape[0],
                                         shuffle=False,
                                         steps_per_epoch=1,
                                         data=[norm_data, norm_labels])

        scores = self.keras_model.fit_generator(generator=fit_generator,
                                                epochs=1,
                                                verbose=self.verbose,
                                                workers=os.cpu_count(),
                                                use_multiprocessing=MULTIPROCESS_FLAG)

        print(f'Completed Training on Batch, {(time.time() - start_time):.{2}f}s in total')

        return None

    def post_training_checklist_child(self):
        self.keras_model.save(self.fullfilepath + _astroNN_MODEL_NAME)
        print(_astroNN_MODEL_NAME + f' saved to {(self.fullfilepath + _astroNN_MODEL_NAME)}')

        self.hyper_txt.write(f"Dropout Rate: {self.dropout_rate} \n")
        self.hyper_txt.flush()
        self.hyper_txt.close()

        data = {'id': self.__class__.__name__ if self._model_identifier is None else self._model_identifier,
                'pool_length': self.pool_length,
                'filterlen': self.filter_len,
                'filternum': self.num_filters,
                'hidden': self.num_hidden,
                'input': self._input_shape,
                'labels': self._labels_shape,
                'task': self.task,
                'last_layer_activation': self._last_layer_activation,
                'activation': self.activation,
                'input_mean': self.input_mean.tolist(),
                'labels_mean': self.labels_mean.tolist(),
                'input_std': self.input_std.tolist(),
                'labels_std': self.labels_std.tolist(),
                'valsize': self.val_size,
                'targetname': self.targetname,
                'dropout_rate': self.dropout_rate,
                'l1': self.l1,
                'l2': self.l2,
                'maxnorm': self.maxnorm,
                'input_norm_mode': self.input_norm_mode,
                'labels_norm_mode': self.labels_norm_mode,
                'batch_size': self.batch_size}

        with open(self.fullfilepath + '/astroNN_model_parameter.json', 'w') as f:
            json.dump(data, f, indent=4, sort_keys=True)

    def test(self, input_data):
        """
        Use the neural network to do inference

        :param input_data: Data to be inferred with neural network
        :type input_data: ndarray
        :return: prediction and prediction uncertainty
        :rtype: ndarry
        :History: 2017-Dec-06 - Written - Henry Leung (University of Toronto)
        """
        self.has_model_check()
        self.pre_testing_checklist_master()

        input_data = np.atleast_2d(input_data)

        if self.input_normalizer is not None:
            input_array = self.input_normalizer.normalize(input_data, calc=False)
        else:
            # Prevent shallow copy issue
            input_array = np.array(input_data)
            input_array -= self.input_mean
            input_array /= self.input_std

        total_test_num = input_data.shape[0]  # Number of testing data

        # for number of training data smaller than batch_size
        if input_data.shape[0] < self.batch_size:
            self.batch_size = input_data.shape[0]

        # Due to the nature of how generator works, no overlapped prediction
        data_gen_shape = (total_test_num // self.batch_size) * self.batch_size
        remainder_shape = total_test_num - data_gen_shape  # Remainder from generator

        predictions = np.zeros((total_test_num, self._labels_shape))

        start_time = time.time()
        print("Starting Inference")

        # Data Generator for prediction
        prediction_generator = CNNPredDataGenerator(batch_size=self.batch_size,
                                                    shuffle=False,
                                                    steps_per_epoch=input_array.shape[0] // self.batch_size,
                                                    data=[input_array[:data_gen_shape]])
        predictions[:data_gen_shape] = np.asarray(self.keras_model.predict_generator(prediction_generator))

        if remainder_shape != 0:
            remainder_data = input_array[data_gen_shape:]
            # assume its caused by mono images, so need to expand dim by 1
            if len(input_array[0].shape) != len(self._input_shape):
                remainder_data = np.expand_dims(remainder_data, axis=-1)
            result = self.keras_model.predict(remainder_data)
            predictions[data_gen_shape:] = result.reshape((remainder_shape, self._labels_shape))

        if self.labels_normalizer is not None:
            predictions = self.labels_normalizer.denormalize(predictions)
        else:
            predictions *= self.labels_std
            predictions += self.labels_mean

        print(f'Completed Inference, {(time.time() - start_time):.{2}f}s elapsed')

        return predictions

    def evaluate(self, input_data, labels):
        """
        Evaluate neural network by provided input data and labels and get back a metrics score

        :param input_data: Data to be inferred with neural network
        :type input_data: ndarray
        :param labels: labels
        :type labels: ndarray
        :return: metrics score dictionary
        :rtype: dict
        :History: 2018-May-20 - Written - Henry Leung (University of Toronto)
        """
        self.has_model_check()
        # check if exists (exists mean fine-tuning, so we do not need calculate mean/std again)
        if self.input_normalizer is None:
            self.input_normalizer = Normalizer(mode=self.input_norm_mode)
            self.labels_normalizer = Normalizer(mode=self.labels_norm_mode)

            norm_data = self.input_normalizer.normalize(input_data)
            self.input_mean, self.input_std = self.input_normalizer.mean_labels, self.input_normalizer.std_labels
            norm_labels = self.labels_normalizer.normalize(labels)
            self.labels_mean, self.labels_std = self.labels_normalizer.mean_labels, self.labels_normalizer.std_labels
        else:
            norm_data = self.input_normalizer.normalize(input_data, calc=False)
            norm_labels = self.labels_normalizer.normalize(labels, calc=False)

        eval_batchsize = self.batch_size if input_data.shape[0] > self.batch_size else input_data.shape[0]
        steps = input_data.shape[0] // self.batch_size if input_data.shape[0] > self.batch_size else 1

        start_time = time.time()
        print("Starting Evaluation")

        evaluate_generator = CNNDataGenerator(batch_size=eval_batchsize,
                                              shuffle=False,
                                              steps_per_epoch=steps,
                                              data=[norm_data, norm_labels])

        scores = self.keras_model.evaluate_generator(evaluate_generator)
        outputname = self.keras_model.output_names
        funcname = []
        if isinstance(self.keras_model.metrics, dict):
            func_list = self.keras_model.metrics[outputname[0]]
        else:
            func_list = self.keras_model.metrics
        for func in func_list:
            if hasattr(func, __name__):
                funcname.append(func.__name__)
            else:
                funcname.append(func.__class__.__name__)
        # funcname = [func.__name__ for func in self.keras_model.metrics]
        output_funcname = [outputname[0] + '_' + name for name in funcname]
        list_names = ['loss', *output_funcname]

        print(f'Completed Evaluation, {(time.time() - start_time):.{2}f}s elapsed')

        return {name: score for name, score in zip(list_names, scores)}
