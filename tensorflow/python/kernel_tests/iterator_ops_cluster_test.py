# Copyright 2017 The TensorFlow Authors. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ==============================================================================
"""Tests for the experimental input pipeline ops that need test_util."""
from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

from tensorflow.core.protobuf import config_pb2
from tensorflow.python.client import session
from tensorflow.python.data.ops import dataset_ops
from tensorflow.python.data.ops import iterator_ops
from tensorflow.python.framework import dtypes
from tensorflow.python.framework import errors
from tensorflow.python.framework import function
from tensorflow.python.framework import ops
from tensorflow.python.framework import test_util
from tensorflow.python.ops import array_ops
from tensorflow.python.ops import functional_ops
from tensorflow.python.platform import test


class IteratorClusterTest(test.TestCase):

  def testRemoteIteratorWithoutRemoteCallFail(self):
    worker_config = config_pb2.ConfigProto()
    worker_config.device_count["CPU"] = 2
    worker, _ = test_util.create_local_cluster(
        1, 1, worker_config=worker_config)

    with ops.device("/job:worker/replica:0/task:0/cpu:1"):
      dataset_3 = dataset_ops.Dataset.from_tensor_slices([1, 2, 3])
      iterator_3 = dataset_3.make_one_shot_iterator()
      iterator_3_handle = iterator_3.string_handle()

    with ops.device("/job:worker/replica:0/task:0/cpu:0"):
      remote_it = iterator_ops.Iterator.from_string_handle(
          iterator_3_handle, dataset_3.output_types, dataset_3.output_shapes)
      get_next_op = remote_it.get_next()

    with session.Session(worker[0].target) as sess:
      with self.assertRaises(errors.InvalidArgumentError):
        sess.run(get_next_op)

  def testRemoteIteratorUsingRemoteCallOp(self):
    worker_config = config_pb2.ConfigProto()
    worker_config.device_count["CPU"] = 2
    worker, _ = test_util.create_local_cluster(
        1, 1, worker_config=worker_config)

    with ops.device("/job:worker/replica:0/task:0/cpu:1"):
      dataset_3 = dataset_ops.Dataset.from_tensor_slices([1, 2, 3])
      iterator_3 = dataset_3.make_one_shot_iterator()
      iterator_3_handle = iterator_3.string_handle()

    @function.Defun(dtypes.string)
    def _remote_fn(h):
      remote_iterator = iterator_ops.Iterator.from_string_handle(
          h, dataset_3.output_types, dataset_3.output_shapes)
      return remote_iterator.get_next()

    with ops.device("/job:worker/replica:0/task:0/cpu:0"):
      target_placeholder = array_ops.placeholder(dtypes.string, shape=[])
      remote_op = functional_ops.remote_call(
          args=[iterator_3_handle],
          Tout=[dtypes.int32],
          f=_remote_fn,
          target=target_placeholder)

    with session.Session(worker[0].target) as sess:
      elem = sess.run(
          remote_op,
          feed_dict={target_placeholder: "/job:worker/replica:0/task:0/cpu:1"})
      self.assertEqual(elem, [1])
      # Fails when target is cpu:0 where the resource is not located.
      with self.assertRaises(errors.InvalidArgumentError):
        sess.run(
            remote_op,
            feed_dict={
                target_placeholder: "/job:worker/replica:0/task:0/cpu:0"
            })
      elem = sess.run(
          remote_op,
          feed_dict={target_placeholder: "/job:worker/replica:0/task:0/cpu:1"})
      self.assertEqual(elem, [2])
      elem = sess.run(
          remote_op,
          feed_dict={target_placeholder: "/job:worker/replica:0/task:0/cpu:1"})
      self.assertEqual(elem, [3])
      with self.assertRaises(errors.OutOfRangeError):
        sess.run(
            remote_op,
            feed_dict={
                target_placeholder: "/job:worker/replica:0/task:0/cpu:1"
            })


if __name__ == "__main__":
  test.main()
