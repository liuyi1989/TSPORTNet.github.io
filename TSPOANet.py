﻿import tensorflow as tf
import vgg16
import cv2
import numpy as np

import multiprocessing
import os

import tensorflow.contrib.slim as slim
from config import cfg

#import sys
#import importlib
#importlib.reload(sys)

img_size = 352
label_size = img_size
#os.environ['CUDA_VISIBLE_DEVICES'] = "0"


class Model:
    def __init__(self):
        self.vgg = vgg16.Vgg16()

        self.input_holder = tf.placeholder(tf.float32, [1, img_size, img_size, 3])
        self.label_holder = tf.placeholder(tf.float32, [label_size*label_size, 2])

        self.sobel_fx, self.sobel_fy = self.sobel_filter()

        self.contour_th = 1.5
        self.contour_weight = 0.0001

    def build_model(self):

        #build the VGG-16 model
        vgg = self.vgg
        vgg.build(self.input_holder)

        fea_dim = 128
        data_size = 88
        weights_regularizer = tf.contrib.layers.l2_regularizer(5e-04)
        
        
        # Local Score
        self.Fea_P5 = self.dilation(vgg.conv5_3, 512, fea_dim/4, 'Fea_P5')
        self.Fea_P4 = self.dilation(vgg.conv4_3, 512, fea_dim/4, 'Fea_P4')
        self.Fea_P3 = self.dilation(vgg.conv3_3, 256, fea_dim/4, 'Fea_P3')
        self.Fea_P2 = self.dilation(vgg.conv2_2, 128, fea_dim/4, 'Fea_P2')
        self.Fea_P1 = self.dilation(vgg.conv1_2, 64, fea_dim/4, 'Fea_P1')


        
        
        self.Fea_P5_Up = tf.nn.relu(self.Deconv_2d(self.Fea_P5, [1, 44, 44, fea_dim], 5, 2, name='Fea_P5_Deconv'))
        self.Fea_P4_Concat = self.Conv_2d(tf.concat([self.Fea_P4, self.Fea_P5_Up], axis=3), [1, 1, fea_dim*2, fea_dim], 0.01, padding='VALID', name='Fea_P4_Concat')
        
        self.Fea_P4_Concat_Up = tf.nn.relu(self.Deconv_2d(self.Fea_P4_Concat, [1, 88, 88, fea_dim], 5, 2, name='Fea_P4_Concat_Deconv'))
        self.Fea_P3_Concat = self.Conv_2d(tf.concat([self.Fea_P3, self.Fea_P4_Concat_Up], axis=3), [1, 1, fea_dim*2, fea_dim], 0.01, padding='VALID', name='Fea_P3_Concat')  
        
        self.Fea_P3_Concat_Up = tf.nn.relu(self.Deconv_2d(self.Fea_P3_Concat, [1, 176, 176, fea_dim], 5, 2, name='Fea_P2_Concat_Deconv'))
        self.Fea_P2_Concat = self.Conv_2d(tf.concat([self.Fea_P2, self.Fea_P3_Concat_Up], axis=3), [1, 1, fea_dim*2, fea_dim], 0.01, padding='VALID', name='Fea_P2_Concat')

        self.Fea_P2_Concat_Up = tf.nn.relu(self.Deconv_2d(self.Fea_P2_Concat, [1, 352, 352, fea_dim], 5, 2, name='Fea_P1_Concat_Deconv'))
        self.Fea_P1_Concat = tf.nn.relu(self.Conv_2d(tf.concat([self.Fea_P1, self.Fea_P2_Concat_Up], axis=3), [1, 1, fea_dim*2, fea_dim], 0.01, padding='VALID', name='Fea_P1_Concat') )
        #self.Fea_P1_Concat = self.Conv_2d(self.Fea_P1, [1, 1, fea_dim, fea_dim], 0.01, padding='VALID', name='Fea_P1_Concat') 
        
        
        

        with tf.variable_scope('relu_conv1') as scope:
            self.output = slim.conv2d(self.Fea_P1_Concat, num_outputs=fea_dim, kernel_size=[
                                 3, 3], stride=2, padding='SAME', scope='deconv', activation_fn=tf.nn.relu)  
            self.output = slim.conv2d(self.output, num_outputs=cfg.B, kernel_size=[
                        3, 3], stride=2, padding='SAME', scope=scope, activation_fn=tf.nn.relu)
            #data_size = int(np.floor((data_size - 4) / 2))
 
        with tf.variable_scope('primary_caps') as scope:
            pose = slim.conv2d(self.output, num_outputs=cfg.B * 16,
                               kernel_size=[1, 1], stride=1, padding='VALID', scope=scope, activation_fn=None)
            activation = slim.conv2d(self.output, num_outputs=cfg.B, kernel_size=[
                                     1, 1], stride=1, padding='VALID', scope='primary_caps/activation', activation_fn=tf.nn.sigmoid)
            pose = tf.reshape(pose, shape=[cfg.batch_size, data_size, data_size, cfg.B, 16])
            activation = tf.reshape(
                activation, shape=[cfg.batch_size, data_size, data_size, cfg.B, 1])
            self.output = tf.concat([pose, activation], axis=4)
           
            
        
            
            #data_size = int(np.floor((data_size - 2) / 2))
            data_size = int(np.floor(data_size / 2))
            
            self.output_Primary_conv1 = tf.split(self.output, num_or_size_splits=2,axis=3)
            
        for i in range(2):
            with tf.variable_scope('conv_caps1'+str(i)) as scope:
                self.output = tf.reshape(self.output_Primary_conv1[i], shape=[cfg.batch_size, data_size*2, data_size*2, -1])
                self.output = self.kernel_tile(self.output, 3, 2)
                self.output = tf.reshape(self.output, shape=[cfg.batch_size *
                                                                     data_size * data_size, 3 * 3 * int(np.floor(cfg.B/2)), 17])
                activation = tf.reshape(self.output[:, :, 16], 
                                        shape=[cfg.batch_size * data_size * data_size, int(np.floor(3 * 3 * cfg.B/2)), 1])
            
                with tf.variable_scope('v'+str(i)) as scope:
                    votes = self.mat_transform(self.output[:, :, :16], int(np.floor(cfg.C/2)), weights_regularizer, tag=True)
            
                with tf.variable_scope('routing'+str(i)) as scope:
                    miu, activation, _ = self.em_routing(votes, activation, int(np.floor(cfg.C/2)), weights_regularizer)
            
                pose = tf.reshape(miu, shape=[cfg.batch_size, data_size, data_size, int(np.floor(cfg.C/2)), 16])
                activation = tf.reshape(
                            activation, shape=[cfg.batch_size, data_size, data_size, int(np.floor(cfg.C/2)), 1])   
                self.output = tf.reshape(tf.concat([pose, activation], axis=4), [
                                cfg.batch_size, data_size, data_size, -1])
                
            with tf.variable_scope('conv_caps2'+str(i)) as scope:
                self.output = self.kernel_tile(self.output, 3, 1)
                #data_size = int(np.floor(data_size / 2))
                self.output = tf.reshape(self.output, shape=[cfg.batch_size *
                                                                             data_size * data_size, 3 * 3 * int(np.floor(cfg.C/2)), 17]) 
                activation = tf.reshape(self.output[:, :, 16], shape=[
                                    cfg.batch_size * data_size * data_size, 3 * 3 * int(np.floor(cfg.C/2)), 1])
            
                with tf.variable_scope('v'+str(i)) as scope:
                    votes = self.mat_transform(self.output[:, :, :16], int(np.floor(cfg.D/2)), weights_regularizer)
            
                with tf.variable_scope('routing'+str(i)) as scope:
                    miu, activation, _ = self.em_routing(votes, activation, int(np.floor(cfg.D/2)), weights_regularizer)
            
                pose = tf.reshape(miu, shape=[cfg.batch_size * data_size * data_size, int(np.floor(cfg.D/2)), 16])
                activation = tf.reshape(
                                    activation, shape=[cfg.batch_size * data_size * data_size, int(np.floor(cfg.D/2)), 1])
                if i==0:
                    self.pose_conv2 = pose
                    self.activation_conv2 = activation
                else:
                    self.pose_conv2 = tf.concat([self.pose_conv2, pose], axis=1)
                    self.activation_conv2 = tf.concat([self.activation_conv2, activation], axis=1)                
            

        with tf.variable_scope('class_caps') as scope:
            with tf.variable_scope('v') as scope:
                votes = self.mat_transform(self.pose_conv2, 2, weights_regularizer)

                #coord_add = np.reshape(coord_add, newshape=[data_size * data_size, 1, 1, 2])
                #coord_add = np.tile(coord_add, [cfg.batch_size, cfg.D, num_classes, 1])
                #coord_add_op = tf.constant(coord_add, dtype=tf.float32)

                #votes = tf.concat([coord_add_op, votes], axis=3)

            with tf.variable_scope('routing') as scope:
                miu, activation, test2 = self.em_routing(
                    votes, self.activation_conv2, 2, weights_regularizer)
                tf.summary.histogram(name="class_cap_routing_hist",
                                     values=test2)

            self.output = tf.reshape(activation, shape=[
                                cfg.batch_size, data_size, data_size, 2])
            
            
            
            self.output_Up1 = tf.nn.relu(self.Deconv_2d(self.output,
                                                            [1, 88, 88, fea_dim], 5, 2, name='output_Deconv1'))
            self.output_Up2 = tf.nn.relu(self.Deconv_2d(self.output_Up1,
                                                                [1, 176, 176, fea_dim], 5, 2, name='output_Deconv2'))  
            self.output_Up3 = tf.nn.relu(self.Deconv_2d(self.output_Up2,
                                                                [1, 352, 352, fea_dim], 5, 2, name='output_Deconv3'))   
            
            self.output_Score = self.Conv_2d(self.output_Up3, [1, 1, fea_dim, 2], 0.01, padding='VALID', name='output_Score')        

        self.Score = tf.reshape(self.output_Score, [-1,2])

        self.Prob = tf.nn.softmax(self.Score)

        #Get the contour term
        self.Prob_C = tf.reshape(self.Prob, [1, 352, 352, 2])
        self.Prob_Grad = tf.tanh(self.im_gradient(self.Prob_C))
        self.Prob_Grad = tf.tanh(tf.reduce_sum(self.im_gradient(self.Prob_C), reduction_indices=3, keep_dims=True))

        self.label_C = tf.reshape(self.label_holder, [1, 352, 352, 2])
        self.label_Grad = tf.cast(tf.greater(self.im_gradient(self.label_C), self.contour_th), tf.float32)
        self.label_Grad = tf.cast(tf.greater(tf.reduce_sum(self.im_gradient(self.label_C),
                                                           reduction_indices=3, keep_dims=True),
                                             self.contour_th), tf.float32)

        self.C_IoU_LOSS = self.Loss_IoU(self.Prob_Grad, self.label_Grad)

        #self.Contour_Loss = self.Loss_Contour(self.Prob_Grad, self.label_Grad)

        #Loss Function
        self.Loss_Mean = self.C_IoU_LOSS \
                         + tf.reduce_mean(tf.nn.softmax_cross_entropy_with_logits(logits=self.Score,
                                                                                  labels=self.label_holder))
                                                                                  
        #self.Loss_Mean = tf.reduce_mean(tf.nn.softmax_cross_entropy_with_logits(logits=self.Score,
                                                                                  #labels=self.label_holder))

        self.correct_prediction = tf.equal(tf.argmax(self.Score,1), tf.argmax(self.label_holder, 1))
        self.accuracy = tf.reduce_mean(tf.cast(self.correct_prediction, tf.float32))

    def Conv_2d(self, input_, shape, stddev, name, padding='SAME'):
        with tf.variable_scope(name) as scope:
            W = tf.get_variable('W',
                                shape=shape,
                                initializer=tf.truncated_normal_initializer(stddev=stddev))

            conv = tf.nn.conv2d(input_, W, [1, 1, 1, 1], padding=padding)

            b = tf.Variable(tf.constant(0.0, shape=[shape[3]]), name='b')
            conv = tf.nn.bias_add(conv, b)

            return conv

    def Deconv_2d(self, input_, output_shape,
                  k_s=3, st_s=2, stddev=0.01, padding='SAME', name="deconv2d"):
        with tf.variable_scope(name):
            W = tf.get_variable('W',
                                shape=[k_s, k_s, output_shape[3], input_.get_shape()[3]],
                                initializer=tf.random_normal_initializer(stddev=stddev))

            deconv = tf.nn.conv2d_transpose(input_, W, output_shape=output_shape,
                                            strides=[1, st_s, st_s, 1], padding=padding)

            b = tf.get_variable('b', [output_shape[3]], initializer=tf.constant_initializer(0.0))
            deconv = tf.nn.bias_add(deconv, b)

        return deconv

    def Contrast_Layer(self, input_, k_s=3):
        h_s = int(k_s / 2)
        return tf.subtract(input_, tf.nn.avg_pool(tf.pad(input_, [[0, 0], [h_s, h_s], [h_s, h_s], [0, 0]], 'SYMMETRIC'),
                                                  ksize=[1, k_s, k_s, 1], strides=[1, 1, 1, 1], padding='VALID'))

    def sobel_filter(self):
        fx = np.array([[-1, 0, 1], [-2, 0, 2], [-1, 0, 1]]).astype(np.float32)
        fy = np.array([[-1, -2, -1], [0, 0, 0], [1, 2, 1]]).astype(np.float32)

        fx = np.stack((fx, fx), axis=2)
        fy = np.stack((fy, fy), axis=2)

        fx = np.reshape(fx, (3, 3, 2, 1))
        fy = np.reshape(fy, (3, 3, 2, 1))

        tf_fx = tf.Variable(tf.constant(fx))
        tf_fy = tf.Variable(tf.constant(fy))

        return tf_fx, tf_fy

    def im_gradient(self, im):
        gx = tf.nn.depthwise_conv2d(tf.pad(im, [[0, 0], [1, 1], [1, 1], [0, 0]], 'SYMMETRIC'),
                                    self.sobel_fx, [1, 1, 1, 1], padding='VALID')
        gy = tf.nn.depthwise_conv2d(tf.pad(im, [[0, 0], [1, 1], [1, 1], [0, 0]], 'SYMMETRIC'),
                                    self.sobel_fy, [1, 1, 1, 1], padding='VALID')
        return tf.sqrt(tf.add(tf.square(gx), tf.square(gy)))

    def Loss_IoU(self, pred, gt):
        inter = tf.reduce_sum(tf.multiply(pred, gt))
        union = tf.add(tf.reduce_sum(tf.square(pred)), tf.reduce_sum(tf.square(gt)))

        if inter == 0:
            return 0
        else:
            return 1 - (2*(inter+1)/(union + 1))

    def Loss_Contour(self, pred, gt):
        return tf.reduce_mean(-gt*tf.log(pred+0.00001) - (1-gt)*tf.log(1-pred+0.00001))

    def L2(self, tensor, wd=0.0005):
        return tf.mul(tf.nn.l2_loss(tensor), wd, name='L2-Loss')
    
    def kernel_tile(self, input, kernel, stride):
        # output = tf.extract_image_patches(input, ksizes=[1, kernel, kernel, 1], strides=[1, stride, stride, 1], rates=[1, 1, 1, 1], padding='VALID')
    
        input_shape = input.get_shape()
        tile_filter = np.zeros(shape=[kernel, kernel, input_shape[3],
                                      kernel * kernel], dtype=np.float32)
        for i in range(kernel):
            for j in range(kernel):
                tile_filter[i, j, :, i * kernel + j] = 1.0
    
        tile_filter_op = tf.constant(tile_filter, dtype=tf.float32)
        output = tf.nn.depthwise_conv2d(input, tile_filter_op, strides=[
                                        1, stride, stride, 1], padding='SAME')
        output_shape = output.get_shape()
        output = tf.reshape(output, shape=[int(output_shape[0]), int(
            output_shape[1]), int(output_shape[2]), int(input_shape[3]), kernel * kernel])
        output = tf.transpose(output, perm=[0, 1, 2, 4, 3])
    
        return output   
    
    def dilation(self, input, input_dim, output_dim, name):
        with tf.variable_scope(name) as scope:
            a = tf.nn.relu(self.Atrous_conv2d(input, [3, 3, input_dim, output_dim], 1, 0.01, name = 'dilation1'))
            b = tf.nn.relu(self.Atrous_conv2d(input, [3, 3, input_dim, output_dim], 3, 0.01, name = 'dilation3'))
            c = tf.nn.relu(self.Atrous_conv2d(input, [3, 3, input_dim, output_dim], 5, 0.01, name = 'dilation5'))
            d = tf.nn.relu(self.Atrous_conv2d(input, [3, 3, input_dim, output_dim], 7, 0.01, name = 'dilation7'))
            e = tf.concat([a, b, c, d], axis = 3)
            
        return e
    
    def Atrous_conv2d(self, input, shape, rate, stddev, name, padding = 'SAME'):
        with tf.variable_scope(name):
            W = tf.get_variable('W',
                                shape = shape,
                                initializer = tf.truncated_normal_initializer(stddev = stddev))
            atrous_conv = tf.nn.atrous_conv2d(input, W, rate = rate, padding = padding)
            b = tf.get_variable('b', shape = [shape[3]], initializer = tf.constant_initializer(0.0))
            atrous_conv = tf.nn.bias_add(atrous_conv, b)
            
        return atrous_conv    
    
    
    def mat_transform(self, input, caps_num_c, regularizer, tag=False):
        batch_size = int(input.get_shape()[0])
        caps_num_i = int(input.get_shape()[1])
        output = tf.reshape(input, shape=[batch_size, caps_num_i, 1, 4, 4])
        # the output of capsule is miu, the mean of a Gaussian, and activation, the sum of probabilities
        # it has no relationship with the absolute values of w and votes
        # using weights with bigger stddev helps numerical stability
        w = slim.variable('w', shape=[1, caps_num_i, caps_num_c, 4, 4], dtype=tf.float32,
                          initializer=tf.truncated_normal_initializer(mean=0.0, stddev=1.0),
                          regularizer=regularizer)
    
        w = tf.tile(w, [batch_size, 1, 1, 1, 1])
        output = tf.tile(output, [1, 1, caps_num_c, 1, 1])
        votes = tf.reshape(tf.matmul(output, w), [batch_size, caps_num_i, caps_num_c, 16])
    
        return votes
    
    def em_routing(self, votes, activation, caps_num_c, regularizer, tag=False):
        test = []
    
        batch_size = int(votes.get_shape()[0])
        caps_num_i = int(activation.get_shape()[1])
        n_channels = int(votes.get_shape()[-1])
    
        sigma_square = []
        miu = []
        activation_out = []
        beta_v = slim.variable('beta_v', shape=[caps_num_c, n_channels], dtype=tf.float32,
                               initializer=tf.constant_initializer(0.0),#tf.truncated_normal_initializer(mean=0.0, stddev=0.01),
                               regularizer=regularizer)
        beta_a = slim.variable('beta_a', shape=[caps_num_c], dtype=tf.float32,
                               initializer=tf.constant_initializer(0.0),#tf.truncated_normal_initializer(mean=0.0, stddev=0.01),
                               regularizer=regularizer)
    
        # votes_in = tf.stop_gradient(votes, name='stop_gradient_votes')
        # activation_in = tf.stop_gradient(activation, name='stop_gradient_activation')
        votes_in = votes
        activation_in = activation
    
        for iters in range(cfg.iter_routing):
            # if iters == cfg.iter_routing-1:
    
            # e-step
            if iters == 0:
                r = tf.constant(np.ones([batch_size, caps_num_i, caps_num_c], dtype=np.float32) / caps_num_c)
            else:
                # Contributor: Yunzhi Shi
                # log and exp here provide higher numerical stability especially for bigger number of iterations
                log_p_c_h = -tf.log(tf.sqrt(sigma_square)) - \
                            (tf.square(votes_in - miu) / (2 * sigma_square))
                log_p_c_h = log_p_c_h - \
                            (tf.reduce_max(log_p_c_h, axis=[2, 3], keep_dims=True) - tf.log(10.0))
                p_c = tf.exp(tf.reduce_sum(log_p_c_h, axis=3))
    
                ap = p_c * tf.reshape(activation_out, shape=[batch_size, 1, caps_num_c])
    
                # ap = tf.reshape(activation_out, shape=[batch_size, 1, caps_num_c])
    
                r = ap / (tf.reduce_sum(ap, axis=2, keep_dims=True) + cfg.epsilon)
    
            # m-step
            r = r * activation_in
            r = r / (tf.reduce_sum(r, axis=2, keep_dims=True)+cfg.epsilon)
    
            r_sum = tf.reduce_sum(r, axis=1, keep_dims=True)
            r1 = tf.reshape(r / (r_sum + cfg.epsilon),
                            shape=[batch_size, caps_num_i, caps_num_c, 1])
    
            miu = tf.reduce_sum(votes_in * r1, axis=1, keep_dims=True)
            sigma_square = tf.reduce_sum(tf.square(votes_in - miu) * r1,
                                         axis=1, keep_dims=True) + cfg.epsilon
    
            if iters == cfg.iter_routing-1:
                r_sum = tf.reshape(r_sum, [batch_size, caps_num_c, 1])
                cost_h = (beta_v + tf.log(tf.sqrt(tf.reshape(sigma_square,
                                                             shape=[batch_size, caps_num_c, n_channels])))) * r_sum
    
                activation_out = tf.nn.softmax(cfg.ac_lambda0 * (beta_a - tf.reduce_sum(cost_h, axis=2)))
            else:
                activation_out = tf.nn.softmax(r_sum)
            # if iters <= cfg.iter_routing-1:
            #     activation_out = tf.stop_gradient(activation_out, name='stop_gradient_activation')
    
        return miu, activation_out, test
    


if __name__ == "__main__":

    img = cv2.imread("E:/LY/NLDF-master/dataset/img/1.jpg")

    h, w = img.shape[0:2]
    img = cv2.resize(img, (img_size,img_size)) - vgg16.VGG_MEAN
    img = img.reshape((1, img_size, img_size, 3))

    label = cv2.imread("E:/LY/NLDF-master/dataset/label/1.png")[:, :, 0]
    label = cv2.resize(label, (label_size, label_size))
    label = label.astype(np.float32) / 255
    label = np.stack((label, 1-label), axis=2)
    label = np.reshape(label, [-1, 2])

    sess = tf.Session()

    model = Model()
    model.build_model()

    max_grad_norm = 1
    tvars = tf.trainable_variables()
    grads, _ = tf.clip_by_global_norm(tf.gradients(model.C_IoU_LOSS, tvars), max_grad_norm)
    opt = tf.train.AdamOptimizer(1e-5)
    optimizer = opt.apply_gradients(zip(grads, tvars))

    sess.run(tf.global_variables_initializer())

    for i in range(200):  #python2.x xrange, python3.x range
        _, C_IoU_LOSS = sess.run([optimizer, model.C_IoU_LOSS],
                                 feed_dict={model.input_holder: img,
                                            model.label_holder: label})

        print('[Iter %d] Contour Loss: %f' % (i, C_IoU_LOSS))

    boundary, gt_boundary = sess.run([model.Prob_Grad, model.label_Grad],
                                     feed_dict={model.input_holder: img,
                                                model.label_holder: label})

    boundary = np.squeeze(boundary)
    boundary = cv2.resize(boundary, (w, h))

    gt_boundary = np.squeeze(gt_boundary)
    gt_boundary = cv2.resize(gt_boundary, (w, h))

    cv2.imshow('boundary', np.uint8(boundary*255))
    cv2.imshow('boundary_gt', np.uint8(gt_boundary*255))

    cv2.waitKey()
