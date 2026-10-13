pub const RNG_VERSION: &str = "splitmix64-rejection-v1";
pub struct Rng(pub u64);
impl Rng {
    pub fn next_u64(&mut self) -> u64 {
        self.0 = self.0.wrapping_add(0x9e3779b97f4a7c15);
        let mut z = self.0;
        z = (z ^ (z >> 30)).wrapping_mul(0xbf58476d1ce4e5b9);
        z = (z ^ (z >> 27)).wrapping_mul(0x94d049bb133111eb);
        z ^ (z >> 31)
    }
    pub fn below(&mut self, limit: u64) -> u64 {
        assert!(limit > 0, "random range must be nonzero");
        let threshold = limit.wrapping_neg() % limit;
        loop {
            let value = self.next_u64();
            if value >= threshold {
                return value % limit;
            }
        }
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn fixed_seed_produces_stable_independently_known_sequence() {
        let mut rng = Rng(0);
        assert_eq!(rng.next_u64(), 0xe220a8397b1dcdaf);
        assert_eq!(rng.next_u64(), 0x6e789e6aa1b965f4);
    }
    #[test]
    fn bounded_draws_stay_in_range_and_singleton_is_zero() {
        let mut rng = Rng(7);
        assert_eq!(rng.below(1), 0);
        for _ in 0..1000 {
            assert!(rng.below(11) < 11);
        }
    }
}
