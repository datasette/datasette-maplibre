"""
Builds demo/demo.db, the database for the datasette-maplibre demo.

    uv run python demo/build.py

Source data is downloaded to demo/cache/ the first time this is run.
Use --refresh to download it again, for example for newer earthquakes.
"""

import csv
from datetime import datetime, timezone
import json
import pathlib
import sqlite3
import sys
from urllib.parse import quote
from urllib.request import Request, urlopen

DEMO = pathlib.Path(__file__).parent
CACHE = DEMO / "cache"
DB_PATH = DEMO / "demo.db"
NATURAL_EARTH = (
    "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/"
)
SOURCES = {
    "power_plants.csv": "https://raw.githubusercontent.com/wri/global-power-plant-database/master/output_database/global_power_plant_database.csv",
    "countries.geojson": NATURAL_EARTH + "ne_110m_admin_0_countries.geojson",
    "rivers.geojson": NATURAL_EARTH + "ne_50m_rivers_lake_centerlines.geojson",
    "places.geojson": NATURAL_EARTH + "ne_110m_populated_places_simple.geojson",
    "earthquakes.geojson": "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/4.5_month.geojson",
}

# name, kind, city, country, year, latitude, longitude, Wikipedia page,
# Wikimedia Commons file, description
LANDMARKS = [
    ("Eiffel Tower", "Tower", "Paris", "France", 1889, 48.8584, 2.2945, "Eiffel_Tower", "Tour_Eiffel_Wikimedia_Commons.jpg", "Wrought-iron lattice tower built for the 1889 World's Fair."),
    ("Empire State Building", "Skyscraper", "New York", "United States", 1931, 40.7484, -73.9857, "Empire_State_Building", "Empire_State_Building_(aerial_view).jpg", "102-storey Art Deco skyscraper, the tallest building in the world until 1970."),
    ("Sydney Opera House", "Building", "Sydney", "Australia", 1973, -33.8568, 151.2153, "Sydney_Opera_House", "Sydney_Opera_House_-_Dec_2008.jpg", "Performing arts centre on Sydney Harbour, designed by Jørn Utzon."),
    ("Golden Gate Bridge", "Bridge", "San Francisco", "United States", 1937, 37.8199, -122.4783, "Golden_Gate_Bridge", "GoldenGateBridge-001.jpg", "Suspension bridge across the strait between San Francisco Bay and the Pacific."),
    ("Colosseum", "Monument", "Rome", "Italy", 80, 41.8902, 12.4922, "Colosseum", "Colosseo_2020.jpg", "The largest ancient amphitheatre ever built."),
    ("Taj Mahal", "Monument", "Agra", "India", 1653, 27.1751, 78.0421, "Taj_Mahal", "Taj_Mahal_(Edited).jpeg", "Ivory-white marble mausoleum on the bank of the Yamuna."),
    ("Sagrada Família", "Building", "Barcelona", "Spain", 1882, 41.4036, 2.1744, "Sagrada_Família", "Sagrada_Familia_01.jpg", "Antoni Gaudí's basilica, under construction since 1882."),
    ("Tower Bridge", "Bridge", "London", "United Kingdom", 1894, 51.5055, -0.0754, "Tower_Bridge", "Tower_Bridge_from_Shad_Thames.jpg", "Combined bascule and suspension bridge over the Thames."),
    ("Tokyo Skytree", "Tower", "Tokyo", "Japan", 2012, 35.7101, 139.8107, "Tokyo_Skytree", "Tokyo_Skytree_2014_Ⅲ.jpg", "634 metre broadcasting and observation tower."),
    ("Christ the Redeemer", "Monument", "Rio de Janeiro", "Brazil", 1931, -22.9519, -43.2105, "Christ_the_Redeemer_(statue)", "Christ_the_Redeemer_-_Cristo_Redentor.jpg", "Art Deco statue at the summit of Mount Corcovado."),
    ("Petronas Towers", "Skyscraper", "Kuala Lumpur", "Malaysia", 1998, 3.1579, 101.7116, "Petronas_Towers", "Petronas_Twin_Towers_2010_April.jpg", "88-storey twin towers, the tallest buildings in the world until 2004."),
    ("Brandenburg Gate", "Monument", "Berlin", "Germany", 1791, 52.5163, 13.3777, "Brandenburg_Gate", "Brandenburger_Tor_abends.jpg", "Neoclassical city gate at the end of Unter den Linden."),
    ("CN Tower", "Tower", "Toronto", "Canada", 1976, 43.6426, -79.3871, "CN_Tower", "CN_Tower_Toronto.jpg", "553 metre concrete communications and observation tower."),
    ("Space Needle", "Tower", "Seattle", "United States", 1962, 47.6205, -122.3493, "Space_Needle", "Space_Needle_2011-07-04.jpg", "Observation tower built for the 1962 World's Fair."),
    ("Machu Picchu", "Monument", "Cusco Region", "Peru", 1450, -13.1631, -72.5450, "Machu_Picchu", "Machu_Picchu,_Peru.jpg", "15th-century Inca citadel in the Andes."),
    ("Statue of Liberty", "Monument", "New York", "United States", 1886, 40.6892, -74.0445, "Statue_of_Liberty", "Statue_of_Liberty_7.jpg", "Copper statue on Liberty Island, a gift from the people of France."),
    ("Table Mountain", "Mountain", "Cape Town", "South Africa", None, -33.9628, 18.4098, "Table_Mountain", "Table_Mountain_DanieVDM.jpg", "Flat-topped mountain overlooking Cape Town."),
    ("Marina Bay Sands", "Building", "Singapore", "Singapore", 2010, 1.2834, 103.8607, "Marina_Bay_Sands", "Marina_Bay_Sands_in_the_evening_-_20101120.jpg", "Three hotel towers joined by a rooftop park."),
]


def fetch(filename, refresh=False):
    path = CACHE / filename
    if refresh or not path.exists():
        CACHE.mkdir(exist_ok=True)
        print("Downloading", SOURCES[filename])
        request = Request(SOURCES[filename], headers={"User-Agent": "datasette-maplibre-demo"})
        with urlopen(request, timeout=120) as response:
            path.write_bytes(response.read())
    return path


def features(filename, refresh=False):
    return json.loads(fetch(filename, refresh).read_text("utf-8"))["features"]


def number(value, cast=float):
    try:
        return cast(float(value))
    except (TypeError, ValueError):
        return None


def build(refresh=False):
    if DB_PATH.exists():
        DB_PATH.unlink()
    db = sqlite3.connect(DB_PATH)

    # Power plants: 35,000 points with a category and a number to colour by
    db.execute(
        """create table power_plants (
            id integer primary key, name text, country text, fuel text,
            capacity_mw float, commissioned integer, owner text,
            latitude float, longitude float
        )"""
    )
    with open(fetch("power_plants.csv", refresh), newline="", encoding="utf-8") as fp:
        db.executemany(
            "insert into power_plants (name, country, fuel, capacity_mw, commissioned,"
            " owner, latitude, longitude) values (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                (
                    row["name"],
                    row["country_long"],
                    row["primary_fuel"],
                    number(row["capacity_mw"]),
                    number(row["commissioning_year"], int),
                    row["owner"] or None,
                    number(row["latitude"]),
                    number(row["longitude"]),
                )
                for row in csv.DictReader(fp)
            ),
        )
    db.execute("create index power_plants_country on power_plants (country)")
    db.execute("create index power_plants_fuel on power_plants (fuel)")
    db.execute("create index power_plants_latitude on power_plants (latitude)")
    db.execute("create index power_plants_longitude on power_plants (longitude)")

    # Earthquakes of the last 30 days
    db.execute(
        """create table earthquakes (
            id text primary key, time text, place text, magnitude float,
            depth_km float, tsunami integer, url text,
            latitude float, longitude float
        )"""
    )
    for feature in features("earthquakes.geojson", refresh):
        properties = feature["properties"]
        longitude, latitude, depth = feature["geometry"]["coordinates"]
        db.execute(
            "insert or replace into earthquakes values (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                feature["id"],
                datetime.fromtimestamp(properties["time"] / 1000, timezone.utc).strftime(
                    "%Y-%m-%d %H:%M"
                ),
                properties["place"],
                properties["mag"],
                depth,
                properties["tsunami"],
                properties["url"],
                latitude,
                longitude,
            ),
        )

    # Countries: polygons, with a category and numbers to colour by
    db.execute(
        """create table countries (
            id integer primary key, name text, iso_a3 text, continent text,
            subregion text, income_group text, population integer,
            gdp_million_usd integer, boundary text
        )"""
    )
    for feature in features("countries.geojson", refresh):
        properties = feature["properties"]
        db.execute(
            "insert into countries (name, iso_a3, continent, subregion, income_group,"
            " population, gdp_million_usd, boundary) values (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                properties["NAME"],
                properties["ADM0_A3"],
                properties["CONTINENT"],
                properties["SUBREGION"],
                properties["INCOME_GRP"],
                number(properties["POP_EST"], int),
                number(properties["GDP_MD"], int),
                json.dumps(feature["geometry"]),
            ),
        )

    # Rivers: lines
    db.execute(
        "create table rivers (id integer primary key, name text, kind text,"
        " scale_rank integer, course text)"
    )
    for feature in features("rivers.geojson", refresh):
        properties = feature["properties"]
        geometry = feature.get("geometry") or {}
        if not properties.get("name") or not geometry.get("coordinates"):
            # One of the rivers has an empty list of coordinates
            continue
        db.execute(
            "insert into rivers (name, kind, scale_rank, course) values (?, ?, ?, ?)",
            (
                properties["name"],
                properties["featurecla"],
                properties["scalerank"],
                json.dumps(feature["geometry"]),
            ),
        )

    # Cities, and a view joining capital cities to the outline of their country
    db.execute(
        """create table cities (
            id integer primary key, name text, country text, iso_a3 text,
            is_capital integer, population integer, latitude float, longitude float
        )"""
    )
    for feature in features("places.geojson", refresh):
        properties = feature["properties"]
        db.execute(
            "insert into cities (name, country, iso_a3, is_capital, population,"
            " latitude, longitude) values (?, ?, ?, ?, ?, ?, ?)",
            (
                properties["name"],
                properties["adm0name"],
                properties["adm0_a3"],
                int(properties["adm0cap"] or 0),
                number(properties["pop_max"], int),
                properties["latitude"],
                properties["longitude"],
            ),
        )
    db.execute(
        """create view capitals_and_countries as
        select
            cities.name as capital, countries.name as country,
            countries.continent, cities.population as capital_population,
            cities.latitude, cities.longitude, countries.boundary
        from cities join countries on cities.iso_a3 = countries.iso_a3
        where cities.is_capital = 1
        order by countries.name"""
    )

    # Landmarks, with a popup column of JSON for datasette-maplibre
    db.execute(
        """create table landmarks (
            id integer primary key, name text, kind text, city text, country text,
            year integer, latitude float, longitude float, popup text
        )"""
    )
    for name, kind, city, country, year, latitude, longitude, page, image, description in LANDMARKS:
        popup = {
            "title": name,
            "image": "https://commons.wikimedia.org/wiki/Special:FilePath/{}?width=400".format(
                quote(image)
            ),
            "alt": "Photograph of " + name,
            "description": description,
            "link": "https://en.wikipedia.org/wiki/" + quote(page),
        }
        db.execute(
            "insert into landmarks (name, kind, city, country, year, latitude,"
            " longitude, popup) values (?, ?, ?, ?, ?, ?, ?, ?)",
            (name, kind, city, country, year, latitude, longitude, json.dumps(popup)),
        )

    db.commit()
    for (table,) in db.execute(
        "select name from sqlite_master where type in ('table', 'view') order by name"
    ).fetchall():
        count = db.execute("select count(*) from [{}]".format(table)).fetchone()[0]
        print("{:>8,}  {}".format(count, table))
    db.execute("vacuum")
    db.close()
    print("Built", DB_PATH)


if __name__ == "__main__":
    build(refresh="--refresh" in sys.argv)
