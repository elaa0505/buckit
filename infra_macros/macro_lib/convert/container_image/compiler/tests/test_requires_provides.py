#!/usr/bin/env python3
'''
Directly tests `requires.py` and `provides.py`, indirectly tests
`path_object.py`.
'''
import unittest

from ..provides import ProvidesDirectory, ProvidesFile
from ..requires import require_directory


class RequiresProvidesTestCase(unittest.TestCase):

    def test_path_normalization(self):
        self.assertEqual('/a', require_directory('a//.').path)
        self.assertEqual('/b/d', ProvidesDirectory(path='/b/c//../d').path)
        self.assertEqual('/x/y', ProvidesFile(path='///x/./y/').path)

    def test_provides_requires(self):
        pf1 = ProvidesFile(path='a')
        pf2 = ProvidesFile(path='a/b')
        pf3 = ProvidesFile(path='a/b/c')
        pd1 = ProvidesDirectory(path='a')
        pd2 = ProvidesDirectory(path='a/b')
        pd3 = ProvidesDirectory(path='a/b/c')
        provides = [pf1, pf2, pf3, pd1, pd2, pd3]

        rd1 = require_directory('a')
        rd2 = require_directory('a/b')
        rd3 = require_directory('a/b/c')
        requires = [rd1, rd2, rd3]

        # Only these will match, everything else cannot.
        provides_matches_requires = {
            (pd1, rd1),
            (pd1, rd2),
            (pd1, rd3),
            (pd2, rd2),
            (pd2, rd3),
            (pd3, rd3),
        }

        # TODO: Use ValidateReqsProvs here once that's committed and tested?
        path_to_reqs_provs = {}
        for p_or_r in (*provides, *requires):
            path_to_reqs_provs.setdefault(p_or_r.path, []).append(p_or_r)

        for p in provides:
            for r in requires:
                # It is an error to match Provides/Requires with distinct paths
                if p.path == r.path:
                    self.assertEqual(
                        (p, r) in provides_matches_requires,
                        p.matches(path_to_reqs_provs, r),
                        f'{p}.match({r})'
                    )
                else:
                    with self.assertRaisesRegex(
                        AssertionError, '^Tried to match .* against .*$'
                    ):
                        p.matches(path_to_reqs_provs, r)


if __name__ == '__main__':
    unittest.main()
