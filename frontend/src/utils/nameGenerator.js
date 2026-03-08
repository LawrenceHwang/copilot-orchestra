/**
 * Generates random <action>-<animal> display names for reviewer agents.
 * Actions and animals are positive/neutral — no violence, vulgarity, or negativity.
 */

const ACTIONS = [
  "bouncing", "dancing", "drifting", "floating", "flying",
  "gliding", "hopping", "leaping", "meandering", "prancing",
  "roaming", "running", "sailing", "singing", "skipping",
  "sliding", "soaring", "spinning", "splashing", "sprinting",
  "stretching", "surfing", "swimming", "twirling", "wandering",
  "whirling", "zooming",
];

const ANIMALS = [
  "badger", "beaver", "buffalo", "camel", "cardinal",
  "chameleon", "crane", "dolphin", "eagle", "elephant",
  "flamingo", "fox", "gecko", "giraffe", "hedgehog",
  "heron", "horse", "hummingbird", "jaguar", "kangaroo",
  "koala", "lemur", "lion", "llama", "lynx",
  "meerkat", "monkey", "moose", "narwhal", "otter",
  "panda", "parrot", "peacock", "penguin", "platypus",
  "puma", "rabbit", "raccoon", "salamander", "seahorse",
  "sloth", "sparrow", "squirrel", "swan", "tiger",
  "toucan", "turtle", "whale", "wolf", "zebra",
];

function pick(arr) {
  return arr[Math.floor(Math.random() * arr.length)];
}

/**
 * Generate `count` unique action-animal names.
 * Uniqueness is guaranteed by set membership — retries on collision.
 */
export function generateReviewerNames(count = 3) {
  const names = new Set();
  while (names.size < count) {
    names.add(`${pick(ACTIONS)}-${pick(ANIMALS)}`);
  }
  return [...names];
}
