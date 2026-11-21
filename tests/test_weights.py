import unittest

from app.services.weights import Entry, WeightError, compute_shares


def free(n=1, share=0):
    return [Entry(share, False, True) for _ in range(n)]


def pinned(share):
    return Entry(share, True, True)


REMOVED = Entry(40, False, False)


class ComputeSharesTest(unittest.TestCase):
    def test_equal_split(self):
        self.assertEqual(compute_shares(free(4)), [25, 25, 25, 25])

    def test_remainder_goes_to_first(self):
        self.assertEqual(compute_shares(free(3)), [34, 33, 33])

    def test_single_offer_gets_everything(self):
        self.assertEqual(compute_shares(free(1)), [100])

    def test_removed_gets_zero(self):
        self.assertEqual(compute_shares([*free(2), REMOVED]), [50, 50, 0])

    def test_pinned_keeps_share(self):
        self.assertEqual(compute_shares([pinned(25), *free(2)]), [25, 38, 37])

    def test_pinned_with_removed(self):
        self.assertEqual(compute_shares([pinned(25), REMOVED, *free(3)]), [25, 0, 25, 25, 25])

    def test_pinned_zero_is_allowed(self):
        self.assertEqual(compute_shares([pinned(0), *free(2)]), [0, 50, 50])

    def test_pins_fill_everything_free_get_zero(self):
        self.assertEqual(compute_shares([pinned(60), pinned(40), *free(2)]), [60, 40, 0, 0])

    def test_all_pinned_summing_to_100(self):
        self.assertEqual(compute_shares([pinned(70), pinned(30)]), [70, 30])

    def test_all_pinned_not_100_fails(self):
        with self.assertRaises(WeightError):
            compute_shares([pinned(70), pinned(20)])

    def test_pins_over_100_fail(self):
        with self.assertRaises(WeightError):
            compute_shares([pinned(70), pinned(40), *free(1)])

    def test_no_active_offers(self):
        self.assertEqual(compute_shares([REMOVED, REMOVED]), [0, 0])

    def test_empty(self):
        self.assertEqual(compute_shares([]), [])

    def test_sum_is_always_100(self):
        for n in range(1, 13):
            for pin in (0, 1, 25, 33, 99):
                shares = compute_shares([pinned(pin), *free(n)])
                self.assertEqual(sum(shares), 100, (n, pin))


if __name__ == "__main__":
    unittest.main()
