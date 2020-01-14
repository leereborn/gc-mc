from __future__ import print_function


from initializations import *
import tensorflow.compat.v1 as tf
tf.disable_v2_behavior()

# global unique layer ID dictionary for layer name assignment
_LAYER_UIDS = {}


def dot(x, y, sparse=False):
    """Wrapper for tf.matmul (sparse vs dense)."""
    if sparse:
        res = tf.sparse_tensor_dense_matmul(x, y)
    else:
        res = tf.matmul(x, y)
    return res


def get_layer_uid(layer_name=''):
    """Helper function, assigns unique layer IDs
    """
    if layer_name not in _LAYER_UIDS:
        _LAYER_UIDS[layer_name] = 1
        return 1
    else:
        _LAYER_UIDS[layer_name] += 1
        return _LAYER_UIDS[layer_name]


def dropout_sparse(x, keep_prob, num_nonzero_elems):
    """Dropout for sparse tensors. Currently fails for very large sparse tensors (>1M elements)
    """
    noise_shape = [num_nonzero_elems]
    random_tensor = keep_prob
    random_tensor += tf.random_uniform(noise_shape)
    dropout_mask = tf.cast(tf.floor(random_tensor), dtype=tf.bool)
    pre_out = tf.sparse_retain(x, dropout_mask)

    return pre_out * tf.div(1., keep_prob)


class Layer(object):
    """Base layer class. Defines basic API for all layer objects.
    # Properties
        name: String, defines the variable scope of the layer.
            Layers with common name share variables. (TODO)
        logging: Boolean, switches Tensorflow histogram logging on/off
    # Methods
        _call(inputs): Defines computation graph of layer
            (i.e. takes input, returns output)
        __call__(inputs): Wrapper for _call()
        _log_vars(): Log all variables
    """

    def __init__(self, **kwargs):
        allowed_kwargs = {'name', 'logging'}
        for kwarg in kwargs.keys():
            assert kwarg in allowed_kwargs, 'Invalid keyword argument: ' + kwarg
        name = kwargs.get('name')
        if not name:
            layer = self.__class__.__name__.lower()
            name = layer + '_' + str(get_layer_uid(layer))
        self.name = name
        self.vars = {}
        logging = kwargs.get('logging', False)
        self.logging = logging
        self.sparse_inputs = False

    def _call(self, inputs):
        return inputs

    def __call__(self, inputs):
        with tf.name_scope(self.name):
            if self.logging and not self.sparse_inputs:
                tf.summary.histogram(self.name + '/inputs', inputs)
            outputs = self._call(inputs)
            if self.logging:
                tf.summary.histogram(self.name + '/outputs', outputs)
            return outputs

    def _log_vars(self):
        for var in self.vars:
            tf.summary.histogram(self.name + '/vars/' + var, self.vars[var])

class Dense(Layer):
    """Dense layer for two types of nodes in a bipartite graph. """

    def __init__(self, input_dim, output_dim, dropout=0., act=tf.nn.relu, share_user_item_weights=False,
                 bias=False, **kwargs):
        super(Dense, self).__init__(**kwargs)
        #input_dim /= 5
        with tf.variable_scope(self.name + '_vars'):
            if not share_user_item_weights:

                self.vars['weights_u'] = weight_variable_random_uniform(input_dim, output_dim, name="weights_u")
                self.vars['weights_v'] = weight_variable_random_uniform(input_dim, output_dim, name="weights_v")

                if bias:
                    self.vars['user_bias'] = bias_variable_truncated_normal([output_dim], name="bias_u")
                    self.vars['item_bias'] = bias_variable_truncated_normal([output_dim], name="bias_v")


            else:
                self.vars['weights_u'] = weight_variable_random_uniform(input_dim, output_dim, name="weights")
                self.vars['weights_v'] = self.vars['weights_u']

                if bias:
                    self.vars['user_bias'] = bias_variable_truncated_normal([output_dim], name="bias_u")
                    self.vars['item_bias'] = self.vars['user_bias']

        self.bias = bias

        self.dropout = dropout
        self.act = act
        if self.logging:
            self._log_vars()

    def _call(self, inputs):
        x_u = inputs[0]
        x_u = tf.nn.dropout(x_u, 1 - self.dropout)
        x_u = tf.matmul(x_u, self.vars['weights_u'])

        x_v = inputs[1]
        x_v = tf.nn.dropout(x_v, 1 - self.dropout)
        x_v = tf.matmul(x_v, self.vars['weights_v'])

        u_outputs = self.act(x_u) #activation
        v_outputs = self.act(x_v)

        if self.bias:
            u_outputs += self.vars['user_bias']
            v_outputs += self.vars['item_bias']

        return u_outputs, v_outputs

    def __call__(self, inputs):
        with tf.name_scope(self.name):
            if self.logging:
                tf.summary.histogram(self.name + '/inputs_u', inputs[0])
                tf.summary.histogram(self.name + '/inputs_v', inputs[1])
            outputs_u, outputs_v = self._call(inputs) #!
            if self.logging:
                tf.summary.histogram(self.name + '/outputs_u', outputs_u)
                tf.summary.histogram(self.name + '/outputs_v', outputs_v)
            return outputs_u, outputs_v

class StackGCN(Layer): # accum resorts to stack
    """Graph convolution layer for bipartite graphs and sparse inputs."""

    def __init__(self, input_dim, output_dim, support, support_t, num_support, u_features_nonzero=None,
                 v_features_nonzero=None, sparse_inputs=False, in_drop=0., dropout=0.,
                 act=tf.nn.relu, share_user_item_weights=True, **kwargs):
        super(StackGCN, self).__init__(**kwargs)

        assert output_dim % num_support == 0, 'output_dim must be multiple of num_support for stackGC layer'

        with tf.variable_scope(self.name + '_vars'):
            self.vars['weights_u'] = weight_variable_random_uniform(input_dim, output_dim, name='weights_u')

            if not share_user_item_weights:
                self.vars['weights_v'] = weight_variable_random_uniform(input_dim, output_dim, name='weights_v')

            else:
                self.vars['weights_v'] = self.vars['weights_u']

        self.weights_u = tf.split(value=self.vars['weights_u'], axis=1, num_or_size_splits=num_support)
        self.weights_v = tf.split(value=self.vars['weights_v'], axis=1, num_or_size_splits=num_support)

        self.dropout = dropout
        self.in_drop = in_drop

        self.sparse_inputs = sparse_inputs #sparse or cold start
        self.u_features_nonzero = u_features_nonzero
        self.v_features_nonzero = v_features_nonzero
        if sparse_inputs:
            assert u_features_nonzero is not None and v_features_nonzero is not None, \
                'u_features_nonzero and v_features_nonzero can not be None when sparse_inputs is True'

        self.support = tf.sparse_split(axis=1, num_split=num_support, sp_input=support) # support of rating levels. Support has been normalized in the global normalization section in trian.py.
        self.support_transpose = tf.sparse_split(axis=1, num_split=num_support, sp_input=support_t)

        self.act = act

        if self.logging:
            self._log_vars()

    def _call(self, inputs):
        x_u = inputs[0]
        x_v = inputs[1]

        if self.sparse_inputs:
            x_u = dropout_sparse(x_u, 1 - self.in_drop, self.u_features_nonzero)
            x_v = dropout_sparse(x_v, 1 - self.in_drop, self.v_features_nonzero)
        else:
            x_u = tf.nn.dropout(x_u, 1 - self.in_drop)
            x_v = tf.nn.dropout(x_v, 1 - self.in_drop)

        supports_u = []
        supports_v = []

        for i in range(len(self.support)): # Equation 8
            tmp_u = dot(x_u, self.weights_u[i], sparse=self.sparse_inputs)
            tmp_v = dot(x_v, self.weights_v[i], sparse=self.sparse_inputs)

            support = self.support[i]
            support_transpose = self.support_transpose[i]

            supports_u.append(tf.sparse_tensor_dense_matmul(support, tmp_v))
            supports_v.append(tf.sparse_tensor_dense_matmul(support_transpose, tmp_u))

        z_u = tf.concat(axis=1, values=supports_u) # The summation in Eq. 8 is replaced by concatenation.
        z_v = tf.concat(axis=1, values=supports_v)

        u_outputs = self.act(z_u)
        v_outputs = self.act(z_v)

        return u_outputs, v_outputs

    def __call__(self, inputs):
        with tf.name_scope(self.name):
            if self.logging and not self.sparse_inputs:
                tf.summary.histogram(self.name + '/inputs_u', inputs[0])
                tf.summary.histogram(self.name + '/inputs_v', inputs[1])
            outputs_u, outputs_v = self._call(inputs)
            if self.logging:
                tf.summary.histogram(self.name + '/outputs_u', outputs_u)
                tf.summary.histogram(self.name + '/outputs_v', outputs_v)
            return outputs_u, outputs_v

class AttentionalStackGCN(Layer):
    """Graph convolution layer for bipartite graphs and sparse inputs."""

    def __init__(self, list_u, list_v,input_dim, output_dim, support, support_t, num_support, u_features_nonzero=None,
                 v_features_nonzero=None, sparse_inputs=False, ffd_drop=0., attn_drop=0.,
                 act=tf.nn.relu, share_user_item_weights=True, **kwargs):
        super(AttentionalStackGCN, self).__init__(**kwargs) #What does this do?

        #print(input_dim,output_dim) # (None,500)
        #import pdb; pdb.set_trace()

        assert output_dim % num_support == 0, 'output_dim must be multiple of num_support for stackGC layer'

        with tf.variable_scope(self.name + '_vars'):
            self.vars['weights_u'] = weight_variable_random_uniform(input_dim, output_dim, name='weights_u')
            attn1 = tf.get_variable(name='attn_self',shape=(output_dim,1),initializer=tf.glorot_uniform_initializer,regularizer=tf.keras.regularizers.l2(l=0.01))
            attn2 = tf.get_variable(name='attn_neigh',shape=(output_dim,1),initializer=tf.glorot_uniform_initializer,regularizer=tf.keras.regularizers.l2(l=0.01))
            self.vars['attn_weights_0'] = attn1 
            self.vars['attn_weights_1'] = attn2 # Use output dim because since the features are transformed to the output_dim.
            
            if not share_user_item_weights:
                self.vars['weights_v'] = weight_variable_random_uniform(input_dim, output_dim, name='weights_v')

            else:
                self.vars['weights_v'] = self.vars['weights_u']

        self.weights_u = tf.split(value=self.vars['weights_u'], axis=1, num_or_size_splits=num_support)
        self.weights_v = tf.split(value=self.vars['weights_v'], axis=1, num_or_size_splits=num_support)

        self.attn_weights_u = tf.split(value=self.vars['attn_weights_0'], axis=0, num_or_size_splits=num_support)
        self.attn_weights_v = tf.split(value=self.vars['attn_weights_1'], axis=0, num_or_size_splits=num_support)

        self.ffd_drop = ffd_drop
        self.attn_drop = attn_drop

        self.sparse_inputs = sparse_inputs #sparse or cold start
        self.u_features_nonzero = u_features_nonzero
        self.v_features_nonzero = v_features_nonzero
        if sparse_inputs:
            assert u_features_nonzero is not None and v_features_nonzero is not None, \
                'u_features_nonzero and v_features_nonzero can not be None when sparse_inputs is True'

        self.support = tf.sparse_split(axis=1, num_split=num_support, sp_input=support) # support of rating levels. Support has been normalized in the global normalization section in trian.py.
        self.support_transpose = tf.sparse_split(axis=1, num_split=num_support, sp_input=support_t)

        self.act = act

        self.list_u=list_u
        self.list_v=list_v
        
        if self.logging:
            self._log_vars()

    def _call(self, inputs):
        x_u = inputs[0]
        x_v = inputs[1]
        
        if self.sparse_inputs:
            x_u_d = dropout_sparse(x_u, 1 - self.attn_drop, self.u_features_nonzero) 
            x_v_d = dropout_sparse(x_v, 1 - self.attn_drop, self.v_features_nonzero)
        else:
            x_u_d = tf.nn.dropout(x_u, 1 - self.attn_drop) # Is this consistent with the paper? 
            x_v_d = tf.nn.dropout(x_v, 1 - self.attn_drop)
        
        supports_u = [] # support is basically adjacent matrix of a certain rating.
        supports_v = []

        for i in range(len(self.support)): # Equation 8
            tmp_u = dot(x_u, self.weights_u[i], sparse=self.sparse_inputs)
            tmp_v = dot(x_v, self.weights_v[i], sparse=self.sparse_inputs)

            support = self.support[i]
            support_transpose = self.support_transpose[i]
            
            attn_for_u = dot(tmp_u,self.attn_weights_u[i])
            attn_for_v = dot(tmp_v,self.attn_weights_v[i])
           
            attn_coef_u = attn_for_u + tf.transpose(attn_for_v) #(943, 1682)
            attn_coef_v = tf.transpose(attn_coef_u) #(1682, 943)
            attn_coef_u = tf.gather(attn_coef_u,self.list_u)
            attn_coef_v = tf.gather(attn_coef_v,self.list_v)

            # Add non-linearty
            attn_coef_u = tf.nn.leaky_relu(attn_coef_u)
            attn_coef_v = tf.nn.leaky_relu(attn_coef_v)
            
            sparse_supp = tf.sparse.reorder(support)
            sparse_supp_t = tf.sparse.reorder(support_transpose)
            dense_supp = tf.sparse.to_dense(sparse_supp)
            dense_supp_t = tf.sparse.to_dense(sparse_supp_t)

            mask_supp = -10e9 * (1.0 - dense_supp)
            attn_coef_u += mask_supp
            mask_supp_t = -10e9 * (1.0 - dense_supp_t)
            attn_coef_v += mask_supp_t

            # Apply softmax to coefficients
            attn_coef_u = tf.nn.softmax(attn_coef_u)
            attn_coef_v = tf.nn.softmax(attn_coef_v)

            # Apply dropout
            #tmp_u = tf.nn.dropout(tmp_u,rate=self.ffd_drop)
            #tmp_v = tf.nn.dropout(tmp_v,rate=self.ffd_drop)
            #tmp_u = tf.nn.dropout(tmp_u,rate=self.attn_drop)
            #tmp_v = tf.nn.dropout(tmp_v,rate=self.attn_drop)
            attn_coef_u = tf.nn.dropout(attn_coef_u,rate=self.attn_drop)
            attn_coef_v = tf.nn.dropout(attn_coef_v,rate=self.attn_drop)
            
            supports_u.append(tf.linalg.matmul(attn_coef_u, tmp_v))
            supports_v.append(tf.linalg.matmul(attn_coef_v, tmp_u))

        z_u = tf.concat(axis=1, values=supports_u) # The summation in Eq. 8 is replaced by concatenation.
        z_v = tf.concat(axis=1, values=supports_v)

        u_outputs = self.act(z_u)
        v_outputs = self.act(z_v)

        return u_outputs, v_outputs

    def __call__(self, inputs): # implementation of function call operator
        with tf.name_scope(self.name):
            if self.logging and not self.sparse_inputs:
                tf.summary.histogram(self.name + '/inputs_u', inputs[0])
                tf.summary.histogram(self.name + '/inputs_v', inputs[1])
            outputs_u, outputs_v = self._call(inputs)
            if self.logging:
                tf.summary.histogram(self.name + '/outputs_u', outputs_u)
                tf.summary.histogram(self.name + '/outputs_v', outputs_v)
            return outputs_u, outputs_v

class OrdinalMixtureGCN(Layer): # Section 2.7 Weight sharing

    """Graph convolution layer for bipartite graphs and sparse inputs."""

    def __init__(self, input_dim, output_dim, support, support_t, num_support, u_features_nonzero=None,
                 v_features_nonzero=None, sparse_inputs=False, in_drop=0., dropout=0.,
                 act=tf.nn.relu, bias=False, share_user_item_weights=False, self_connections=False, **kwargs):
        super(OrdinalMixtureGCN, self).__init__(**kwargs)

        with tf.variable_scope(self.name + '_vars'):

            self.vars['weights_u'] = tf.stack([weight_variable_random_uniform(input_dim, output_dim,
                                                                             name='weights_u_%d' % i)
                                              for i in range(num_support)], axis=0)

            if bias:
                self.vars['bias_u'] = bias_variable_const([output_dim], 0.01, name="bias_u")

            if not share_user_item_weights:
                self.vars['weights_v'] = tf.stack([weight_variable_random_uniform(input_dim, output_dim,
                                                                                 name='weights_v_%d' % i)
                                                  for i in range(num_support)], axis=0)

                if bias:
                    self.vars['bias_v'] = bias_variable_const([output_dim], 0.01, name="bias_v")

            else:
                self.vars['weights_v'] = self.vars['weights_u']
                if bias:
                    self.vars['bias_v'] = self.vars['bias_u']

        self.weights_u = self.vars['weights_u']
        self.weights_v = self.vars['weights_v']

        self.dropout = dropout
        self.in_drop = in_drop

        self.sparse_inputs = sparse_inputs
        self.u_features_nonzero = u_features_nonzero
        self.v_features_nonzero = v_features_nonzero
        if sparse_inputs:
            assert u_features_nonzero is not None and v_features_nonzero is not None, \
                'u_features_nonzero and v_features_nonzero can not be None when sparse_inputs is True'

        self.self_connections = self_connections

        self.bias = bias
        support = tf.sparse_split(axis=1, num_split=num_support, sp_input=support)

        support_t = tf.sparse_split(axis=1, num_split=num_support, sp_input=support_t)

        if self_connections:
            self.support = support[:-1]
            self.support_transpose = support_t[:-1]
            self.u_self_connections = support[-1]
            self.v_self_connections = support_t[-1]
            self.weights_u = self.weights_u[:-1]
            self.weights_v = self.weights_v[:-1]
            self.weights_u_self_conn = self.weights_u[-1]
            self.weights_v_self_conn = self.weights_v[-1]

        else:
            self.support = support
            self.support_transpose = support_t
            self.u_self_connections = None
            self.v_self_connections = None
            self.weights_u_self_conn = None
            self.weights_v_self_conn = None

        self.support_nnz = [] #What is this that never gets used?
        self.support_transpose_nnz = []
        for i in range(len(self.support)):
            nnz = tf.reduce_sum(tf.shape(self.support[i].values))
            self.support_nnz.append(nnz)
            self.support_transpose_nnz.append(nnz)

        self.act = act

        if self.logging:
            self._log_vars()

    def _call(self, inputs):

        if self.sparse_inputs:
            x_u = dropout_sparse(inputs[0], 1 - self.in_drop, self.u_features_nonzero)
            x_v = dropout_sparse(inputs[1], 1 - self.in_drop, self.v_features_nonzero)
        else:
            x_u = tf.nn.dropout(inputs[0], 1 - self.in_drop)
            x_v = tf.nn.dropout(inputs[1], 1 - self.in_drop)

        supports_u = []
        supports_v = []

        # self-connections with identity matrix as support
        if self.self_connections: # Why uw and vw never get used anywhere else?
            uw = dot(x_u, self.weights_u_self_conn, sparse=self.sparse_inputs)
            supports_u.append(tf.sparse_tensor_dense_matmul(self.u_self_connections, uw))

            vw = dot(x_v, self.weights_v_self_conn, sparse=self.sparse_inputs)
            supports_v.append(tf.sparse_tensor_dense_matmul(self.v_self_connections, vw))

        wu = 0.
        wv = 0.
        for i in range(len(self.support)):
            wu += self.weights_u[i]
            wv += self.weights_v[i]

            # multiply feature matrices with weights
            tmp_u = dot(x_u, wu, sparse=self.sparse_inputs)

            tmp_v = dot(x_v, wv, sparse=self.sparse_inputs)

            support = self.support[i]
            support_transpose = self.support_transpose[i]

            # then multiply with rating matrices
            supports_u.append(tf.sparse_tensor_dense_matmul(support, tmp_v))
            supports_v.append(tf.sparse_tensor_dense_matmul(support_transpose, tmp_u))

        z_u = tf.add_n(supports_u)
        z_v = tf.add_n(supports_v)

        if self.bias:
            z_u = tf.nn.bias_add(z_u, self.vars['bias_u'])
            z_v = tf.nn.bias_add(z_v, self.vars['bias_v'])

        u_outputs = self.act(z_u)
        v_outputs = self.act(z_v)

        return u_outputs, v_outputs

    def __call__(self, inputs):
        with tf.name_scope(self.name):
            if self.logging and not self.sparse_inputs:
                tf.summary.histogram(self.name + '/inputs_u', inputs[0])
                tf.summary.histogram(self.name + '/inputs_v', inputs[1])
            outputs_u, outputs_v = self._call(inputs)
            if self.logging:
                tf.summary.histogram(self.name + '/outputs_u', outputs_u)
                tf.summary.histogram(self.name + '/outputs_v', outputs_v)
            return outputs_u, outputs_v

class AttentionalOrdinalMixtureGCN(Layer): # Section 2.7 Weight sharing

    """Graph convolution layer for bipartite graphs and sparse inputs."""

    def __init__(self, list_u, list_v, input_dim, output_dim, support, support_t, num_support, u_features_nonzero=None,
                 v_features_nonzero=None, sparse_inputs=False, attn_drop=0., ffd_drop=0.,
                 act=tf.nn.relu, bias=False, share_user_item_weights=False, self_connections=False, **kwargs):
        super(AttentionalOrdinalMixtureGCN, self).__init__(**kwargs)
        #print(input_dim, output_dim) # (None, 500)
        #import pdb; pdb.set_trace()

        with tf.variable_scope(self.name + '_vars'):

            self.vars['weights_u'] = tf.stack([weight_variable_random_uniform(input_dim, output_dim,
                                                                             name='weights_u_%d' % i)
                                              for i in range(num_support)], axis=0) # Returns an array of weight matrices

            if bias:
                self.vars['bias_u'] = bias_variable_const([output_dim], 0.01, name="bias_u")

            if not share_user_item_weights:
                self.vars['weights_v'] = tf.stack([weight_variable_random_uniform(input_dim, output_dim,
                                                                                 name='weights_v_%d' % i)
                                                  for i in range(num_support)], axis=0)

                if bias:
                    self.vars['bias_v'] = bias_variable_const([output_dim], 0.01, name="bias_v")

            else:
                self.vars['weights_v'] = self.vars['weights_u']
                if bias:
                    self.vars['bias_v'] = self.vars['bias_u']

            for i in range(num_support):
                self.vars['attn_weights_u_{}'.format(i)] = tf.get_variable(name='attn_u_{}'.format(i),shape=(output_dim,1),initializer=tf.glorot_uniform_initializer,regularizer=tf.keras.regularizers.l2(l=0.01))
                self.vars['attn_weights_v_{}'.format(i)] = tf.get_variable(name='attn_v_{}'.format(i),shape=(output_dim,1),initializer=tf.glorot_uniform_initializer,regularizer=tf.keras.regularizers.l2(l=0.01))

        self.weights_u = self.vars['weights_u']
        self.weights_v = self.vars['weights_v']

        self.attn_drop = attn_drop
        self.ffd_drop = ffd_drop

        self.sparse_inputs = sparse_inputs
        self.u_features_nonzero = u_features_nonzero
        self.v_features_nonzero = v_features_nonzero
        if sparse_inputs:
            assert u_features_nonzero is not None and v_features_nonzero is not None, \
                'u_features_nonzero and v_features_nonzero can not be None when sparse_inputs is True'

        self.self_connections = self_connections

        self.bias = bias
        support = tf.sparse_split(axis=1, num_split=num_support, sp_input=support)

        support_t = tf.sparse_split(axis=1, num_split=num_support, sp_input=support_t)

        if self_connections:
            self.support = support[:-1]
            self.support_transpose = support_t[:-1]
            self.u_self_connections = support[-1]
            self.v_self_connections = support_t[-1]
            self.weights_u = self.weights_u[:-1]
            self.weights_v = self.weights_v[:-1]
            self.weights_u_self_conn = self.weights_u[-1]
            self.weights_v_self_conn = self.weights_v[-1]

        else:
            self.support = support
            self.support_transpose = support_t
            self.u_self_connections = None
            self.v_self_connections = None
            self.weights_u_self_conn = None
            self.weights_v_self_conn = None

        self.support_nnz = [] #What is this that never gets used?
        self.support_transpose_nnz = []
        for i in range(len(self.support)):
            nnz = tf.reduce_sum(tf.shape(self.support[i].values))
            self.support_nnz.append(nnz)
            self.support_transpose_nnz.append(nnz)

        self.act = act

        self.list_u=list_u
        self.list_v=list_v

        if self.logging:
            self._log_vars()

    def _call(self, inputs):
        x_u = inputs[0]
        x_v = inputs[1]
        
        if self.sparse_inputs:
            x_u = dropout_sparse(inputs[0], 1 - self.attn_drop, self.u_features_nonzero)
            x_v = dropout_sparse(inputs[1], 1 - self.attn_drop, self.v_features_nonzero)
        else:
            x_u = tf.nn.dropout(inputs[0], 1 - self.attn_drop)
            x_v = tf.nn.dropout(inputs[1], 1 - self.attn_drop)
        
        supports_u = []
        supports_v = []

        #print(self.self_connections) # False
        #import pdb; pdb.set_trace()
        # self-connections with identity matrix as support
        if self.self_connections: # Why append to supports?
            uw = dot(x_u, self.weights_u_self_conn, sparse=self.sparse_inputs)
            supports_u.append(tf.sparse_tensor_dense_matmul(self.u_self_connections, uw))

            vw = dot(x_v, self.weights_v_self_conn, sparse=self.sparse_inputs)
            supports_v.append(tf.sparse_tensor_dense_matmul(self.v_self_connections, vw))

        wu = 0.
        wv = 0.
        for i in range(len(self.support)):
            wu += self.weights_u[i]
            wv += self.weights_v[i]

            # multiply feature matrices with weights
            tmp_u = dot(x_u, wu, sparse=self.sparse_inputs)
            tmp_v = dot(x_v, wv, sparse=self.sparse_inputs)

            support = self.support[i]
            support_transpose = self.support_transpose[i]

            # attn implementation
            attn_for_u = dot(tmp_u,self.vars['attn_weights_u_{}'.format(i)])
            attn_for_v = dot(tmp_v,self.vars['attn_weights_v_{}'.format(i)])
           
            attn_coef_u = attn_for_u + tf.transpose(attn_for_v)
            attn_coef_v = tf.transpose(attn_coef_u)
            attn_coef_u = tf.gather(attn_coef_u,self.list_u)
            attn_coef_v = tf.gather(attn_coef_v,self.list_v)

            # Add non-linearty
            attn_coef_u = tf.nn.leaky_relu(attn_coef_u)
            attn_coef_v = tf.nn.leaky_relu(attn_coef_v)
            
            sparse_supp = tf.sparse.reorder(support)
            sparse_supp_t = tf.sparse.reorder(support_transpose)
            dense_supp = tf.sparse.to_dense(sparse_supp)
            dense_supp_t = tf.sparse.to_dense(sparse_supp_t)

            mask_supp = -10e9 * (1.0 - dense_supp)
            attn_coef_u += mask_supp
            mask_supp_t = -10e9 * (1.0 - dense_supp_t)
            attn_coef_v += mask_supp_t

            # Apply softmax to coefficients
            attn_coef_u = tf.nn.softmax(attn_coef_u)
            attn_coef_v = tf.nn.softmax(attn_coef_v)

            # Apply dropout
            #tmp_u = tf.nn.dropout(tmp_u,rate=self.ffd_drop)
            #tmp_v = tf.nn.dropout(tmp_v,rate=self.ffd_drop)
            attn_coef_u = tf.nn.dropout(attn_coef_u,rate=self.attn_drop)
            attn_coef_v = tf.nn.dropout(attn_coef_v,rate=self.attn_drop)
            # then multiply with rating matrices
            supports_u.append(tf.linalg.matmul(attn_coef_u, tmp_v))
            supports_v.append(tf.linalg.matmul(attn_coef_v, tmp_u))

        z_u = tf.add_n(supports_u)
        z_v = tf.add_n(supports_v)
        #z_u = tf.concat(axis=1, values=supports_u) # The summation in Eq. 8 is replaced by concatenation.
        #z_v = tf.concat(axis=1, values=supports_v)

        #print(self.bias)
        #import pdb; pdb.set_trace()
        if self.bias: #False
            z_u = tf.nn.bias_add(z_u, self.vars['bias_u'])
            z_v = tf.nn.bias_add(z_v, self.vars['bias_v'])

        u_outputs = self.act(z_u)
        v_outputs = self.act(z_v)

        return u_outputs, v_outputs

    def __call__(self, inputs):
        with tf.name_scope(self.name):
            if self.logging and not self.sparse_inputs:
                tf.summary.histogram(self.name + '/inputs_u', inputs[0])
                tf.summary.histogram(self.name + '/inputs_v', inputs[1])
            outputs_u, outputs_v = self._call(inputs)
            if self.logging:
                tf.summary.histogram(self.name + '/outputs_u', outputs_u)
                tf.summary.histogram(self.name + '/outputs_v', outputs_v)
            return outputs_u, outputs_v
            
class BilinearMixture(Layer):
    """
    Decoder model layer for link-prediction with ratings
    To use in combination with bipartite layers.
    """

    def __init__(self, num_classes, u_indices, v_indices, input_dim, num_users, num_items, user_item_bias=False,
                 dropout=0., act=tf.nn.softmax, num_weights=3,
                 diagonal=True, **kwargs):
        super(BilinearMixture, self).__init__(**kwargs)
        with tf.variable_scope(self.name + '_vars'):

            for i in range(num_weights):
                if diagonal:
                    #  Diagonal weight matrices for each class stored as vectors
                    self.vars['weights_%d' % i] = weight_variable_random_uniform(1, input_dim, name='weights_%d' % i)

                else:
                    self.vars['weights_%d' % i] = orthogonal([input_dim, input_dim], name='weights_%d' % i)

            self.vars['weights_scalars'] = weight_variable_random_uniform(num_weights, num_classes,
                                                                          name='weights_u_scalars')

            if user_item_bias:
                self.vars['user_bias'] = bias_variable_zero([num_users, num_classes], name='user_bias')
                self.vars['item_bias'] = bias_variable_zero([num_items, num_classes], name='item_bias')

        self.user_item_bias = user_item_bias

        if diagonal:
            self._multiply_inputs_weights = tf.multiply
        else:
            self._multiply_inputs_weights = tf.matmul

        self.num_classes = num_classes
        self.num_weights = num_weights
        self.u_indices = u_indices
        self.v_indices = v_indices

        self.dropout = dropout
        self.act = act
        if self.logging:
            self._log_vars()

    def _call(self, inputs):

        u_inputs = tf.nn.dropout(inputs[0], 1 - self.dropout)
        v_inputs = tf.nn.dropout(inputs[1], 1 - self.dropout)

        u_inputs = tf.gather(u_inputs, self.u_indices) # u_indices?
        v_inputs = tf.gather(v_inputs, self.v_indices)

        if self.user_item_bias:
            u_bias = tf.gather(self.vars['user_bias'], self.u_indices)
            v_bias = tf.gather(self.vars['item_bias'], self.v_indices)
        else:
            u_bias = None
            v_bias = None

        basis_outputs = []
        for i in range(self.num_weights):

            u_w = self._multiply_inputs_weights(u_inputs, self.vars['weights_%d' % i])
            x = tf.reduce_sum(tf.multiply(u_w, v_inputs), axis=1)

            basis_outputs.append(x)

        # Store outputs in (Nu x Nv) x num_classes tensor and apply activation function
        basis_outputs = tf.stack(basis_outputs, axis=1)

        outputs = tf.matmul(basis_outputs,  self.vars['weights_scalars'], transpose_b=False)

        if self.user_item_bias:
            outputs += u_bias
            outputs += v_bias

        outputs = self.act(outputs) # Why no activation for decoder in paper?

        return outputs

    def __call__(self, inputs):
        with tf.name_scope(self.name):
            if self.logging and not self.sparse_inputs:
                tf.summary.histogram(self.name + '/inputs_u', inputs[0])
                tf.summary.histogram(self.name + '/inputs_v', inputs[1])

            outputs = self._call(inputs)
            if self.logging:
                tf.summary.histogram(self.name + '/outputs', outputs)
            return outputs
