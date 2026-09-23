// What happens when you click something.
//
// One interaction, on purpose: pressing the button picks a new accent colour, and
// everything using --accent changes at once because styles.css names that colour in
// exactly one place.
//
// Nothing here talks to the internet.

const COLOURS = ["#2f6f4f", "#8a4b2a", "#3a5ba0", "#7a2f5f", "#b07d1a"];

const button = document.getElementById("surprise");

button.addEventListener("click", () => {
  const pick = COLOURS[Math.floor(Math.random() * COLOURS.length)];
  document.documentElement.style.setProperty("--accent", pick);
});
