# Copyright 2024 The Orbax Authors.
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

"""Test for utils module."""

from typing import Any, Mapping, NamedTuple, Sequence

from absl.testing import absltest
from absl.testing import parameterized
from etils import epath
import flax
import jax
import numpy as np
import optax
from orbax.checkpoint import test_utils
from orbax.checkpoint._src.testing import test_tree_utils
from orbax.checkpoint._src.tree import utils as tree_utils


Diff = tree_utils.Diff
PyTree = tree_utils.PyTree


class Record(NamedTuple):
  first: Any
  second: Any


def _as_string_equality(a, b) -> bool:
  if a is None or b is None:
    return a == b
  return str(a) == str(b)


# TODO: b/365169723 - Add tests: PyTreeMetadataOptions.support_rich_types=True.
class SerializeTreeTest(parameterized.TestCase):

  def setUp(self):
    super().setUp()
    self.directory = epath.Path(
        self.create_tempdir(name='serialize_tree_test').full_path
    )

  def test_serialize(self):
    tree = {'a': 1, 'b': {'c': {'d': 2}}, 'e': [1, {'x': 5, 'y': 7}, [9, 10]]}
    serialized = tree_utils.serialize_tree(tree, keep_empty_nodes=True)
    self.assertDictEqual(tree, serialized)
    deserialized = tree_utils.deserialize_tree(
        serialized, target=tree, keep_empty_nodes=True
    )
    test_utils.assert_tree_equal(self, tree, deserialized)

  def test_serialize_empty(self):
    serialized = tree_utils.serialize_tree({}, keep_empty_nodes=True)
    test_utils.assert_tree_equal(self, {}, serialized)
    deserialized = tree_utils.deserialize_tree(
        serialized, target={}, keep_empty_nodes=True
    )
    test_utils.assert_tree_equal(self, {}, deserialized)

  def test_serialize_empty_no_keep_empty(self):
    with self.assertRaises(ValueError):
      tree_utils.serialize_tree({}, keep_empty_nodes=False)

  def test_serialize_single_element(self):
    tree = {}
    serialized = tree_utils.serialize_tree(12345, keep_empty_nodes=True)
    test_utils.assert_tree_equal(self, 12345, serialized)
    deserialized = tree_utils.deserialize_tree(
        serialized, target=tree, keep_empty_nodes=True
    )
    test_utils.assert_tree_equal(self, 12345, deserialized)

  def test_serialize_list(self):
    tree = [1, {'a': 2}, [3, 4]]
    serialized = tree_utils.serialize_tree(tree, keep_empty_nodes=True)
    self.assertListEqual(tree, serialized)
    deserialized = tree_utils.deserialize_tree(
        serialized, target=tree, keep_empty_nodes=True
    )
    test_utils.assert_tree_equal(self, tree, deserialized)

  def test_serialize_filters_empty(self):
    tree = {'a': 1, 'b': None, 'c': {}, 'd': [], 'e': optax.EmptyState()}
    serialized = tree_utils.serialize_tree(tree, keep_empty_nodes=False)
    self.assertDictEqual({'a': 1}, serialized)
    deserialized = tree_utils.deserialize_tree(
        serialized, target=tree, keep_empty_nodes=False
    )
    test_utils.assert_tree_equal(self, tree, deserialized)

  def test_serialize_class(self):
    @flax.struct.dataclass
    class Foo(flax.struct.PyTreeNode):
      a: int
      b: Mapping[str, str]
      c: Sequence[optax.EmptyState]
      d: Sequence[Mapping[str, str]]

    foo = Foo(
        1,
        {'a': 'b', 'c': 'd'},
        [optax.EmptyState(), optax.EmptyState()],
        [{}, {'x': 'y'}, None],
    )
    serialized = tree_utils.serialize_tree(foo, keep_empty_nodes=True)
    expected = {
        'a': 1,
        'b': {'a': 'b', 'c': 'd'},
        'c': [optax.EmptyState(), optax.EmptyState()],
        'd': [{}, {'x': 'y'}, None],
    }
    self.assertDictEqual(expected, serialized)
    deserialized = tree_utils.deserialize_tree(
        serialized, target=foo, keep_empty_nodes=False
    )
    test_utils.assert_tree_equal(self, foo, deserialized)

  def test_serialize_nested_class(self):
    @flax.struct.dataclass
    class Foo(flax.struct.PyTreeNode):
      a: int

    nested = {
        'x': Foo(a=1),
        'y': {'z': Foo(a=2)},
    }
    serialized = tree_utils.serialize_tree(nested, keep_empty_nodes=True)
    expected = {
        'x': dict(a=1),
        'y': {'z': dict(a=2)},
    }
    self.assertDictEqual(expected, serialized)


class UtilsTest(parameterized.TestCase):

  def setUp(self):
    super().setUp()
    self.directory = epath.Path(
        self.create_tempdir(name='checkpointing_test').full_path
    )

  @parameterized.parameters(
      ({'a': 1, 'b': {'c': {}, 'd': 2}}, {('a',): 1, ('b', 'd'): 2}),
      ({'x': ['foo', 'bar']}, {('x', '0'): 'foo', ('x', '1'): 'bar'}),
  )
  def test_to_flat_dict(self, tree, expected):
    self.assertDictEqual(expected, tree_utils.to_flat_dict(tree))

  @parameterized.parameters(
      ({'a': 1, 'b': {'d': 2}}, {('a',): 1, ('b', 'd'): 2}),
      ({'x': ['foo', 'bar']}, {('x', '0'): 'foo', ('x', '1'): 'bar'}),
      ({'a': 1, 'b': 2}, {('b',): 2, ('a',): 1}),
  )
  def test_from_flat_dict(self, expected, flat_dict):
    empty = jax.tree.map(lambda _: 0, expected)
    self.assertDictEqual(
        expected, tree_utils.from_flat_dict(flat_dict, target=empty)
    )

  @parameterized.parameters(
      ({'a': 1, 'b': {'d': 2}}, {('a',): 1, ('b', 'd'): 2}),
      ({'a': 1, 'b': 2}, {('b',): 2, ('a',): 1}),
  )
  def test_from_flat_dict_without_target(self, expected, flat_dict):
    self.assertDictEqual(expected, tree_utils.from_flat_dict(flat_dict))

  @parameterized.parameters(
      ({'a': 1, 'b': {'d': 2}}, {'a': 1, 'b/d': 2}),
      ({'a': 1, 'b': 2}, {'b': 2, 'a': 1}),
      ({'a': {'b': {'c': 1}}}, {'a/b/c': 1}),
  )
  def test_from_flat_dict_with_sep(self, expected, flat_dict):
    self.assertDictEqual(
        expected, tree_utils.from_flat_dict(flat_dict, sep='/')
    )

  @parameterized.parameters(
      (1, True, False),
      (np.zeros(1), True, False),
      (dict(), True, True),
      ({}, True, True),
      ({'a': {}}, False, False),
      ([], True, True),
      ([[]], False, False),
      ([tuple()], False, False),
      ([dict()], False, False),
      ([{}], False, False),
      ([1], False, False),
      (tuple(), True, True),
      ((tuple(),), False, False),
      (([],), False, False),
      (({},), False, False),
      ((dict(),), False, False),
      ((1,), False, False),
      (None, True, True),
      ((1, 2), False, False),
      (test_tree_utils.EmptyNamedTuple(), True, True),
      (optax.EmptyState(), True, True),
      (test_tree_utils.MuNu(mu=None, nu=None), False, False),
      (test_tree_utils.MyEmptyClass(), True, False),
      (test_tree_utils.MyClass(), True, False),
      (test_tree_utils.MyClass(a=None, b=None), True, False),
      (test_tree_utils.MyClass(a=None, b=np.zeros(1)), True, False),
      (test_tree_utils.MyEmptyChex(), True, True),
      (test_tree_utils.MyChex(), False, False),
      (
          test_tree_utils.MyChex(my_jax_array=None, my_np_array=None),
          False,
          False,
      ),
      (
          test_tree_utils.MyChex(my_jax_array=None, my_np_array=np.zeros(1)),
          False,
          False,
      ),
      (test_tree_utils.MyEmptyFlax(), True, True),
      (test_tree_utils.MyFlax(), False, False),
      (
          test_tree_utils.MyFlax(
              my_jax_array=None, my_nested_mapping=None, my_sequence=None
          ),
          False,
          False,
      ),
      (test_tree_utils.MyFlax(my_nested_mapping={'a': 1}), False, False),
      (test_tree_utils.MyEmptyDataClass(), True, False),
      (test_tree_utils.MyDataClass(), True, False),
      (
          test_tree_utils.MyDataClass(
              my_jax_array=None,
              my_np_array=None,
              my_empty_dataclass=None,
              my_chex=None,
          ),
          True,
          False,
      ),
  )
  def test_is_empty_or_leaf(
      self,
      value: Any,
      expected_is_empty_or_leaf: bool,
      expected_is_empty_node: bool,
  ):
    self.assertEqual(
        expected_is_empty_or_leaf, tree_utils.is_empty_or_leaf(value)
    )
    self.assertEqual(expected_is_empty_node, tree_utils.is_empty_node(value))

  @parameterized.parameters(
      (test_tree_utils.EmptyNamedTuple(),),
      (test_tree_utils.IntegerNamedTuple(None, None),),
      (test_tree_utils.IntegerNamedTuple(1, 2),),
  )
  def test_named_tuple_type_detection(self, nt):
    self.assertTrue(tree_utils.isinstance_of_namedtuple(nt))
    self.assertTrue(tree_utils.issubclass_of_namedtuple(type(nt)))

  @parameterized.parameters(
      ((1, 2),),
      ({'a': 1, 'b': 2},),
      ([1, 2],),
  )
  def test_non_named_tuple_type_detection(self, nt):
    self.assertFalse(tree_utils.isinstance_of_namedtuple(nt))
    self.assertFalse(tree_utils.issubclass_of_namedtuple(type(nt)))

  @parameterized.parameters(
      (
          {'a': 100, 'b': [200, {'c': 300}]},
          {'a': 1, 'b': [2, {'c': 3}]},
          {'a': 1, 'b': [2, {'c': 3}]},
      ),
      (
          {'a': 100, 'b': [200, {'c': 300}]},
          {'a': 1, 'b': [2, {'c': 3, 'd': 4}], 'e': 5},
          {'a': 1, 'b': [2, {'c': 3}]},
      ),
      (
          {'a': [100, 200], 'b': {'c': 300}},
          {'a': (1, 2), 'b': {'c': 3, 'd': 4}},
          {'a': [1, 2], 'b': {'c': 3}},
      ),
      (
          {},
          {'a': 1, 'b': 2},
          {},
      ),
      (
          {},
          {},
          {},
      ),
  )
  def test_tree_trim_valid(
      self, template: PyTree, structure: PyTree, expected: PyTree
  ):
    self.assertDictEqual(expected, tree_utils.tree_trim(template, structure))

  @parameterized.parameters(
      int,
      float,
      complex,
      str,
      bytes,
      bool,
      np.int32,
      np.float32,
  )
  def test_tree_trim_leaves(self, val_type: Any):
    val = val_type()
    self.assertEqual(val, tree_utils.tree_trim(val, val))

  def test_tree_trim_extra_path_in_structure(self):
    structure = {'a': 1, 'b': [2, {'c': 3}]}

    template = {'a': 100, 'b': [200, {'c': 300, 'd': 400}], 'e': 500}
    with self.assertRaisesRegex(ValueError, 'Path "b.1.d" exists in template'):
      tree_utils.tree_trim(template, structure)

    template = {'a': 100, 'b': [200, {'c': 300}], 'e': 500}
    with self.assertRaisesRegex(ValueError, 'Path "e" exists in template'):
      tree_utils.tree_trim(template, structure)

  def test_tree_trim_empty_template(self):
    structure = {}
    template = {'a': 1, 'b': 2}
    with self.assertRaisesRegex(ValueError, 'Path "a" exists in template'):
      tree_utils.tree_trim(template, structure)

  def test_tree_trim_mismatch_structure(self):
    structure = 10
    template = {'a': 20}
    with self.assertRaisesRegex(ValueError, 'Path "a" exists in template'):
      tree_utils.tree_trim(template, structure)

  def test_tree_trim_mismatch_template(self):
    structure = {'a': 10}
    template = 20
    with self.assertRaisesRegex(ValueError, 'Path "" exists in template'):
      tree_utils.tree_trim(template, structure)

  def test_tree_trim_v2_custom_node(self):
    @flax.struct.dataclass
    class SimpleData:
      x: int
      y: str

    structure = {'data': SimpleData(x=1, y='hello'), 'other': 10}
    template = {'data': SimpleData(x=100, y='world')}
    expected = {'data': SimpleData(x=1, y='hello')}

    result = tree_utils.tree_trim(template, structure)
    test_utils.assert_tree_equal(self, expected, result)


class TreeDifferenceTest(parameterized.TestCase):

  def test_doc_example(self):
    first = {'x': [1, 2, 3], 'y': 'same', 'z': {'p': {}, 'q': 4, 'r': 6}}
    second = {'x': [1, 3], 'y': 'same', 'z': {'p': {}, 'q': 5, 's': 6}}
    actual = tree_utils.tree_difference(first, second)
    expected = {
        'x': Diff(lhs=(list, 3), rhs=(list, 2)),
        'z': {
            'r': Diff(lhs=6, rhs=None),
            's': Diff(lhs=None, rhs=6),
        },
    }
    self.assertEqual(actual, expected)

  def test_uses_leaves_equal_predicate(self):
    first = {'x': [1, 2, 3], 'y': 'same', 'z': {'p': {}, 'q': 4, 'r': 6}}
    second = {'x': [1, 2, 3], 'y': 'same', 'z': {'p': {}, 'q': 4, 's': 6}}
    leaf_equality_fn = lambda x, y: x == y

    actual = tree_utils.tree_difference(
        first, second, leaves_equal=leaf_equality_fn
    )
    expected = {'z': {'r': Diff(lhs=6, rhs=None), 's': Diff(lhs=None, rhs=6)}}
    self.assertEqual(actual, expected)

  @parameterized.parameters([
      ((),),
      ([],),
      ({},),
      ((1, 2, 3),),  # tuples of same elements.
      (
          (1, 2, 3),
          (2, 3, 4),
      ),  # tuples of same length using type equality.
      ([1, 2, 3],),
      (
          [1, 2, 3],
          [2, 3, 4],
      ),  # lists of same length using type equality.
      ({'one': 1, 'two': 2, 'three': 3},),
      (Record(first=1, second=2),),
  ])
  def test_match_returns_none(self, lhs, rhs=None):
    if rhs is None:
      rhs = lhs
    self.assertIsNone(tree_utils.tree_difference(lhs, rhs))

  @parameterized.parameters([
      ('abc', 'abc'),
      (123, 123),
      (123, '123'),
      ('123', 123),
  ])
  def test_match_returns_none_custom_equality_fn(self, lhs, rhs):
    self.assertIsNone(
        tree_utils.tree_difference(lhs, rhs, leaves_equal=_as_string_equality)
    )

  @parameterized.parameters([('abc', 'bcd'), (123, 234), (123, '123')])
  def test_match_returns_diff_custom_equality_fn(self, lhs, rhs):
    self.assertEqual(
        tree_utils.tree_difference(lhs, rhs, leaves_equal=lambda x, y: x == y),
        Diff(lhs=lhs, rhs=rhs),
    )

  def test_named_tuples_are_compared_fieldwise(self):
    self.assertEqual(
        tree_utils.tree_difference(
            Record(first=3, second=4), Record(first=5, second='four')
        ),
        Record(first=None, second=Diff(lhs=4, rhs='four')),
    )

  def test_named_tuples_are_compared_fieldwise_custom_equality_fn(self):
    self.assertEqual(
        tree_utils.tree_difference(
            Record(first='3', second=4),
            Record(first=3, second='four'),
            leaves_equal=_as_string_equality,
        ),
        Record(first=None, second=Diff(lhs=4, rhs='four')),
    )

  @parameterized.product(
      sequence_type=[tuple, list], eq_fn=[None, lambda x, y: x == y]
  )
  def test_length_difference_is_reported_as_pair_of_type_and_length(
      self, sequence_type, eq_fn
  ):
    s = sequence_type
    self.assertEqual(
        tree_utils.tree_difference(
            s([1, 2, 3]), s(['one', 'two']), leaves_equal=eq_fn
        ),
        Diff(lhs=(s, 3), rhs=(s, 2)),
    )

  @parameterized.parameters(tuple, list)
  def test_element_difference_is_none_at_matching_indices(self, sequence_type):
    s = sequence_type
    self.assertEqual(
        tree_utils.tree_difference(s([1, 2, 3]), s([1, 'two', 2])),
        s([None, Diff(lhs=2, rhs='two'), None]),
    )

  @parameterized.parameters(tuple, list)
  def test_element_difference_is_none_at_matching_indices_custom_equality_fn(
      self, sequence_type
  ):
    s = sequence_type
    leaf_equality_fn = _as_string_equality

    self.assertEqual(
        tree_utils.tree_difference(
            s([1, 2, 3]), s([1, 'two', '3']), leaves_equal=leaf_equality_fn
        ),
        s([None, Diff(lhs=2, rhs='two'), None]),
    )

  def test_mapping_difference_only_contains_mismatched_elements(self):
    self.assertEqual(
        tree_utils.tree_difference(
            {'one': 1, 'two': 2, 'three': 3},
            {'one': 1, 'two': 'two', 'three': 3},
        ),
        {'two': Diff(lhs=2, rhs='two')},
    )

  def test_difference_with_custom_pytree_node(self):
    @flax.struct.dataclass
    class NewModel(flax.struct.PyTreeNode):
      x: Any
      y: Any

    self.assertEqual(
        tree_utils.tree_difference(
            NewModel(
                x=jax.ShapeDtypeStruct(shape=(16,), dtype=np.int64),
                y=Ellipsis,
            ),
            NewModel(
                x=jax.ShapeDtypeStruct(shape=(16,), dtype=np.int64),
                y=jax.ShapeDtypeStruct(shape=(16,), dtype=np.float64),
            ),
        ),
        NewModel(
            x=None,
            y=Diff(
                lhs=Ellipsis,
                rhs=jax.ShapeDtypeStruct(shape=(16,), dtype=np.float64),
            ),
        ),
    )

  def test_uses_is_leaf_to_recognize_leaves(self):

    def custom_is_leaf(x: PyTree) -> bool:
      return isinstance(x, int) or isinstance(x, list)

    first = {
        'x': 0,
        'y': [0],
        'z': {'p': 0, 'q': [0, 1]},
        'w': [0, [1, 2], [3], 4],
    }
    second = {
        'x': 1,
        'y': [1, 2],
        'z': {'p': 1, 'q': [2]},
        'w': [5, [6], [7], 8],
    }

    self.assertEqual(
        tree_utils.tree_difference(first, second),
        {
            'y': Diff(lhs=(list, 1), rhs=(list, 2)),
            'z': {
                'q': Diff(lhs=(list, 2), rhs=(list, 1)),
            },
            'w': [None, Diff(lhs=(list, 2), rhs=(list, 1)), None, None],
        },
    )

    self.assertIsNone(
        tree_utils.tree_difference(first, second, is_leaf=custom_is_leaf)
    )


if __name__ == '__main__':
  absltest.main()
