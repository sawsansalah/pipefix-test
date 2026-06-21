const { add, multiply } = require("../index");

test("adds numbers", () => {
  expect(add(2, 3)).toBe(5);
});

test("multiplies numbers", () => {
  // Deliberate bug: expects the wrong result to produce a clean,
  // demo-friendly Jest failure.
  expect(multiply(2, 3)).toBe(8);
});
