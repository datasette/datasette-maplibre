import datasette
from datasette_test import wait_until_responds
import json
import pytest
import sqlite3
from subprocess import Popen, PIPE
import sys

# An empty style, so that the tests never need to fetch tiles
EMPTY_STYLE = {"version": 8, "sources": {}, "layers": []}
OTHER_STYLE = {
    "version": 8,
    "sources": {},
    "layers": [
        {"id": "background", "type": "background", "paint": {"background-color": "#dde"}}
    ],
}


def pytest_report_header():
    return "Datasette: {}".format(datasette.__version__)


def square(lng, lat, size=0.1):
    return json.dumps(
        {
            "type": "Polygon",
            "coordinates": [
                [
                    [lng, lat],
                    [lng + size, lat],
                    [lng + size, lat + size],
                    [lng, lat + size],
                    [lng, lat],
                ]
            ],
        }
    )


@pytest.fixture(scope="session")
def ds_db_path(tmp_path_factory):
    db_path = str(tmp_path_factory.mktemp("tmp") / "data.db")
    db = sqlite3.connect(db_path)
    with db:
        db.execute(
            "create table two_points (id integer primary key, name text, lat float, lng float)"
        )
        db.execute(
            "insert into two_points (name, lat, lng) values "
            "('Santa Cruz <b>', 37.0167, -122.0024), ('San Jose', 37.3184, -121.9511)"
        )
        # 25 rows, more than the max_returned_rows of 10
        db.execute(
            "create table paginated (id integer primary key, category text, "
            "score integer, latitude float, longitude float)"
        )
        db.executemany(
            "insert into paginated (category, score, latitude, longitude) values (?, ?, ?, ?)",
            [
                (["red", "green", "blue"][i % 3], i * 10, 37.0 + i * 0.01, -122.0 - i * 0.01)
                for i in range(25)
            ],
        )
        db.execute(
            "create table no_locations (id integer primary key, latitude float, longitude float)"
        )
        db.execute("insert into no_locations (latitude, longitude) values (null, null)")
        # Only the last 5 of 25 rows have a location, so none on the first page
        db.execute(
            "create table locations_on_last_page (id integer primary key, latitude float, longitude float)"
        )
        db.executemany(
            "insert into locations_on_last_page (latitude, longitude) values (?, ?)",
            [(None, None)] * 20
            + [(37.0 + i * 0.01, -122.0 - i * 0.01) for i in range(5)],
        )
        db.execute("create table shapes (id integer primary key, name text, geometry text)")
        db.executemany(
            "insert into shapes (name, geometry) values (?, ?)",
            [("Square {}".format(i), square(-122 + i, 37)) for i in range(6)],
        )
        db.execute(
            "create table mixed (id integer primary key, name text, latitude float, "
            "longitude float, boundary text, popup text)"
        )
        db.execute(
            "insert into mixed (name, latitude, longitude, boundary, popup) values (?, ?, ?, ?, ?)",
            (
                "Both",
                37.05,
                -121.95,
                square(-122, 37),
                json.dumps(
                    {
                        "title": "Popup title",
                        "description": "Popup description",
                        "link": "javascript:alert(1)",
                    }
                ),
            ),
        )
    db.close()
    return db_path


@pytest.fixture(scope="session")
def ds_server(ds_db_path, tmp_path_factory):
    metadata_path = tmp_path_factory.mktemp("metadata") / "metadata.json"
    metadata_path.write_text(
        json.dumps(
            {
                "plugins": {
                    "datasette-maplibre": {
                        "style": EMPTY_STYLE,
                        "styles": {"Other": OTHER_STYLE},
                        "max_cell_maps": 2,
                    }
                },
                "databases": {
                    "data": {
                        "tables": {
                            "two_points": {
                                "plugins": {"datasette-maplibre": {"view": "points"}}
                            }
                        }
                    }
                },
            }
        )
    )
    port = 8146
    process = Popen(
        [
            sys.executable,
            "-m",
            "datasette",
            "--port",
            str(port),
            "--setting",
            "max_returned_rows",
            "10",
            "--metadata",
            str(metadata_path),
            str(ds_db_path),
        ],
        stdout=PIPE,
    )
    url = "http://localhost:{}".format(port)
    try:
        wait_until_responds(url + "/")
        yield url
    finally:
        process.terminate()
        process.wait()
