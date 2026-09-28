// Helper for tests/test_js_parity.py: node js_plan.js <config> <routes> <weather> <date> <type>
const fs = require("fs");
const path = require("path");
const P = require(path.join(__dirname, "..", "site", "planner.js"));

const [cfgPath, routesPath, weatherPath, day, rideType] = process.argv.slice(2);
const cfg = JSON.parse(fs.readFileSync(cfgPath, "utf8"));
const routes = JSON.parse(fs.readFileSync(routesPath, "utf8")).routes;
const weather = JSON.parse(fs.readFileSync(weatherPath, "utf8"));
const legs = Object.fromEntries(routes.map((r) => [r.id, P.routeLegs(r)]));
process.stdout.write(JSON.stringify(P.planDay(day, rideType, routes, legs, weather, cfg)));
