import keras
from keras.backend import batch_dot

from Models.BaseModel import BaseModel
from keras.layers import *
from keras.activations import softmax

def unchanged_shape(input_shape):
    """Function for Lambda layer"""
    return input_shape


def batchdot(multituple):
    d = K.batch_dot(multituple[0], multituple[1], axes=[2, 1])
    return d


def batchdot_output_shape(input_shape):
    shape = list(input_shape[1])
    assert len(shape) == 3
    return tuple(shape)

def vec_output_shape(input_shape):
    shape = list(input_shape)
    shape.pop(2)
    assert len(shape) == 2
    return tuple(shape)

def apply_multiple(input_, layers):
    # "Apply layers to input then concatenate result"
    if not len(layers) > 1:
        raise ValueError('Layers list should contain more than 1 layer')
    else:
        agg_ = []
        for layer in layers:
            agg_.append(layer(input_))
        out_ = Concatenate()(agg_)
    return out_


def atten_layer(input):
    attention = Dot(axes=-1)([input, input])
    w_att = Lambda(lambda x: softmax(x, axis=-1),
                   output_shape=unchanged_shape)(attention)
    out = Lambda(batchdot, output_shape=batchdot_output_shape)([w_att, input])

    return out


def submult(input_1, input_2):
    "Get multiplication and subtraction then concatenate results"
    mult = Multiply()([input_1, input_2])
    sub = substract(input_1, input_2)
    out_ = Concatenate()([sub, mult])
    return out_


def substract(input_1, input_2):
    "Substract element-wise"
    neg_input_2 = Lambda(lambda x: -x, output_shape=unchanged_shape)(input_2)
    out_ = Add()([input_1, neg_input_2])
    return out_


def soft_attention_alignment(input_1, input_2):
    """Align text representation with neural soft attention"""

    attention = Dot(axes=-1)([input_1, input_2])

    w_att_1 = Lambda(lambda x: softmax(x, axis=1),
                     output_shape=unchanged_shape)(attention)
    w_att_2 = Permute((2, 1))(Lambda(lambda x: softmax(x, axis=2),
                              output_shape=unchanged_shape)(attention))
    in1_aligned = Dot(axes=1)([w_att_1, input_1])
    in2_aligned = Dot(axes=1)([w_att_2, input_2])
    return in1_aligned, in2_aligned


def get_sentence_vector(input):
    atten_vec = Dense(1)(input)
    atten_vec = Lambda(lambda x: softmax(x, axis=1),
                       output_shape=unchanged_shape)(atten_vec)
    atten_vec = Lambda(lambda x: K.squeeze(x, axis=-1), output_shape=vec_output_shape)(atten_vec)
    sen_vector = Dot(axes=1)([atten_vec, input])

    return sen_vector


def fusion_sentence_atten(input_vec, input_seq):

    input_vec_seq = keras.layers.RepeatVector(43)(input_vec)
    print(input_vec_seq.shape)
    seq = Concatenate()([input_seq,input_vec_seq])

    seq_new = Dense(600)(seq)
    return seq_new


class IAN(BaseModel):


    def embedded(self):
        if self.args.need_word_level:
            shape = self.embedding_matrix.shape
            word_embedding = Embedding(shape[0], shape[1], mask_zero=False,
                                       weights=[self.embedding_matrix], trainable=self.args.word_trainable)
            Q1_emb = word_embedding(self.Q1)
            Q2_emb = word_embedding(self.Q2)
            embedded = [Q1_emb, Q2_emb]
        else:
            embedded = [None, None]

        if self.args.need_char_level:
            shape = self.char_embedding_matrix.shape
            char_embedding = Embedding(*shape, mask_zero=False,
                                       weights=[self.char_embedding_matrix], trainable=self.args.char_trainable)
            Q1_char_emb = char_embedding(self.Q1_char)
            Q2_char_emb = char_embedding(self.Q2_char)
            embedded += [Q1_char_emb, Q2_char_emb]
        else:
            embedded += [None, None]

        return embedded

    def build_model(self):

        BGRU1 = Bidirectional(GRU(300, return_sequences=True,
                                  dropout=0.2, implementation=2))
        BGRU2 = Bidirectional(GRU(300, return_sequences=True,
                                  dropout=0.2, implementation=2))

        encoding1 = BGRU1(self.Q1_emb)
        encoding2 = BGRU1(self.Q2_emb)

        sen1_vector = get_sentence_vector(encoding1)
        sen2_vector = get_sentence_vector(encoding2)

        sen2_new = fusion_sentence_atten(sen1_vector, encoding2)
        sen1_new = fusion_sentence_atten(sen2_vector, encoding1)

        result1 = BGRU2(sen1_new)
        result2 = BGRU2(sen2_new)

        q1_compare = concatenate([result1, sen1_new])
        q2_compare = concatenate([result2, sen2_new])

        q1_rep = apply_multiple(q1_compare, [GlobalAvgPool1D(), GlobalMaxPool1D()])
        q2_rep = apply_multiple(q2_compare, [GlobalAvgPool1D(), GlobalMaxPool1D()])

        mysub = subtract([q1_rep, q2_rep])
        mymut = multiply([q1_rep, q2_rep])
        result = concatenate([q1_rep, q2_rep, mymut, mysub])
        result = Dropout(0.2)(result)
        result = Dense(512, activation='tanh')(result)
        result = Dense(256, activation='tanh')(result)
        predictions = Dense(1, activation='sigmoid')(result)

        return predictions
