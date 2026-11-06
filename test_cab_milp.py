"""Compare direct MILP against exhaustive cyclic labelings on small graphs."""
import itertools
import json
from pathlib import Path
import random
import tempfile
import unittest
import gurobipy as gp
from cab_milp import read_graph, solve, validate_labels


def brute(n, edges):
    return max(validate_labels([0, *tail], edges)
               for tail in itertools.permutations(range(1, n)))


class DirectMILPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.env = gp.Env(empty=True)
        cls.env.setParam('OutputFlag', 0)
        cls.env.start()

    @classmethod
    def tearDownClass(cls):
        cls.env.dispose()

    def test_against_exhaustive(self):
        rng = random.Random(28)
        graphs = []
        # Every nonempty graph through 4 vertices, including disconnected/isolated.
        for n in range(2, 5):
            pairs = list(itertools.combinations(range(n), 2))
            for mask in range(1, 1 << len(pairs)):
                graphs.append((n, [e for j, e in enumerate(pairs) if mask >> j & 1]))
        for n in (5, 6, 7):
            for _ in range(8):
                edges = [e for e in itertools.combinations(range(n), 2) if rng.random() < 0.4]
                graphs.append((n, edges or [(0, 1)]))
        for n, edges in graphs:
            expected = brute(n, edges)
            for cuts in (False, True):
                with self.subTest(n=n, edges=edges, cuts=cuts):
                    result = solve(n, edges, time_limit=10, env=self.env, window_cuts=cuts)
                    self.assertEqual(result['objective'], expected)
                    self.assertEqual(result['upper_bound'], expected)
                    self.assertEqual(result['status'], 'OPTIMAL')
                    self.assertEqual(result['optimize_calls'], 1)
                    self.assertEqual(validate_labels(result['labels'], edges), expected)
        print(f'Checked {len(graphs)} graphs, {2*len(graphs)} solves against brute force', flush=True)

    def test_leaf_symmetry_and_clique(self):
        cases = [(7, [(0, i) for i in range(1, 7)], []),
                 (7, [(0,1),(0,2),(1,2),(3,4),(3,5),(3,6)], [[0,1,2]]),
                 (8, [(0,1)], [])]
        for n, edges, cliques in cases:
            expected = brute(n, edges)
            for symmetry in (False, True):
                result = solve(n, edges, list(reversed(range(n))), cliques, env=self.env,
                               reflection=symmetry, leaf_symmetry=symmetry, window_cuts=True)
                self.assertEqual(result['objective'], expected)

    def test_deadline_fallback(self):
        n = 14
        edges = list(itertools.combinations(range(n), 2))
        result = solve(n, edges, env=self.env, time_limit=1e-9)
        self.assertEqual(validate_labels(result['labels'], edges), result['objective'])
        self.assertEqual(result['optimize_calls'], 1)
        self.assertIsNone(result['gurobi_objective'])

    def test_input_formats(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d)/'graph.txt'
            path.write_text('Comment\n5 5 999\n1 2\n2 1\n')
            n, edges, _, _ = read_graph(path)
            self.assertEqual((n, edges), (5, [(0,1)]))
            path = Path(d)/'graph.json'
            doc = dict(n=5, edges=[[0,1],[1,2],[0,2]], cliques=[[0,1,2]], start=list(range(5)))
            path.write_text(json.dumps(doc)); self.assertEqual(read_graph(path)[0], 5)
            doc['cliques'] = [[0,1,4]]
            path.write_text(json.dumps(doc))
            with self.assertRaises(ValueError): read_graph(path)
            doc['cliques'] = []; doc['edges'] = [[1,1]]
            path.write_text(json.dumps(doc))
            with self.assertRaises(ValueError): read_graph(path)
            doc['edges'] = []
            path.write_text(json.dumps(doc))
            with self.assertRaises(ValueError): read_graph(path)

if __name__ == '__main__':
    unittest.main(verbosity=2)
