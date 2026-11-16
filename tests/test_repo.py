import os
import unittest


class RepoStructureSmokeTest(unittest.TestCase):
    def test_required_paths_exist(self):
        root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        required = [
            "README.md",
            "trader-alerts",
            "trader-analyst",
            "trader-broker",
            "trader-budget",
            "trader-entry",
            "trader-exit",
            "trader-news",
            "trader-pelosi",
            "trader-risk",
            "trader-scanner",
            "trader-timemachine",
            "tests",
        ]
        for path in required:
            self.assertTrue(os.path.exists(os.path.join(root, path)))


if __name__ == "__main__":
    unittest.main()
