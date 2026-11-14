"""Run with: python -m unittest discover -s code -p 'test_*.py'"""
import unittest
from fractions import Fraction
from select_projects import ROOT,percentiles
from verify_dataset import verify_final


class ReproductionTests(unittest.TestCase):
    def test_average_ties(self):
        self.assertEqual(percentiles([10,10,30,100]),[Fraction(50,3),Fraction(50,3),Fraction(200,3),Fraction(100)])

    def test_all_equal(self):
        self.assertEqual(percentiles([7,7,7]),[Fraction(50)]*3)

    def test_frozen_corpus(self):
        report=verify_final(ROOT/'dataset')
        self.assertEqual(report['projects'],300)
        self.assertEqual(report['candidate_occurrences'],1046)


if __name__=='__main__':unittest.main()
