import unittest

from app.models import OfferState, Stream, StreamOffer


def offer(share, state=OfferState.active, published_share=None, published_state=None):
    return StreamOffer(
        offer_id=1, share=share, state=state,
        published_share=published_share, published_state=published_state,
    )


class DirtyTest(unittest.TestCase):
    def test_published_offer_is_clean(self):
        self.assertFalse(offer(50, published_share=50, published_state=OfferState.active).is_dirty)

    def test_new_offer_is_dirty(self):
        self.assertTrue(offer(25).is_dirty)

    def test_share_change_is_dirty(self):
        self.assertTrue(offer(25, published_share=33, published_state=OfferState.active).is_dirty)

    def test_removed_offer_is_dirty_until_published(self):
        o = offer(0, OfferState.removed, published_share=33, published_state=OfferState.active)
        self.assertTrue(o.is_dirty)

    def test_stream_dirty_if_any_offer_dirty(self):
        clean = offer(50, published_share=50, published_state=OfferState.active)
        self.assertFalse(Stream(offers=[clean]).is_dirty)
        self.assertTrue(Stream(offers=[clean, offer(50)]).is_dirty)


if __name__ == "__main__":
    unittest.main()
