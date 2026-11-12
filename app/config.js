// Where the hourly Gold JSON lives. The app itself is deployed rarely (Netlify);
// the data is republished every hour by GitHub Actions to GitHub Pages, which serves it with CORS enabled.
window.PHW_CONFIG = {
  dataBase: (location.hostname === "localhost" || location.hostname === "127.0.0.1")
    ? "./data"
    : "https://dtopgoat.github.io/ph-weather-pipeline/data",
  repoUrl: "https://github.com/DTopGoat/ph-weather-pipeline",
};
