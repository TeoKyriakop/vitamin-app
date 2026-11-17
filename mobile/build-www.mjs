// Copies the built site (../site, from `python -m vitapp.site ../site`) into www/ for the Android app.
// The app reads live data from GitHub Pages and keeps the copy bundled here for offline use.
import {cpSync, rmSync, writeFileSync, readFileSync, existsSync} from "node:fs";
const SITE = new URL("../site/", import.meta.url), WWW = new URL("./www/", import.meta.url);
if (!existsSync(SITE)) throw new Error("Λείπει ο φάκελος site/. Τρέξτε πρώτα: cd server && python -m vitapp.site ../site");
rmSync(WWW, {recursive: true, force: true});
cpSync(SITE, WWW, {recursive: true});
rmSync(new URL("sw.js", WWW), {force: true});   // no service worker inside the app
const cfg = JSON.parse(readFileSync(new URL("config.json", WWW), "utf8"));
cfg.dataBase = process.env.DATA_BASE || "https://teokyriakop.github.io/vitamin-app/";
writeFileSync(new URL("config.json", WWW), JSON.stringify(cfg));
console.log("www ready:", cfg);
