"""Offline checks for errors that could invalidate a historical information set."""

import io
from pathlib import Path
import sys
import unittest
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from download_public_data import DownloadForm, archive_stats, latest_stats, month_ends, snapshot_stats


def archive(rows):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zipped:
        zipped.writestr("README.txt", "Series ID: TEST\nObservations by Real-Time Period\n")
        zipped.writestr("obs.csv", "period_start_date,TEST,realtime_start_date,realtime_end_date\n" + rows)
    return buffer.getvalue()


class DownloadTests(unittest.TestCase):
    def test_missing_is_not_zero_and_negative_spread_is_valid(self):
        result = latest_stats(b"observation_date,TEST\n2020-01-01,.\n2020-01-02,0\n2020-01-03,-1\n", "TEST", "2020-01-01", "2020-01-31")
        self.assertEqual(result["numeric_observations"], 2)
        self.assertEqual(result["missing"], 1)
        self.assertEqual(result["first_valid"], "2020-01-02")

    def test_future_and_duplicate_observations_fail(self):
        for rows in ("2020-02-01,1\n", "2020-01-01,1\n2020-01-01,2\n"):
            with self.assertRaises(ValueError):
                latest_stats(("observation_date,TEST\n" + rows).encode(), "TEST", "2020-01-01", "2020-01-31")

    def test_html_error_or_wrong_series_fails(self):
        with self.assertRaises(ValueError):
            latest_stats(b"<html>error</html>", "TEST", "2020-01-01", "2020-01-31")

    def test_revision_and_missing_deletion_are_retained(self):
        result = archive_stats(archive("2020-01-01,1,2020-02-01,2020-02-28\n2020-01-01,.,2020-02-29,\n"), "TEST", "2020-01-01", "2020-02-29", ["2020-02-01", "2020-02-29"])
        self.assertEqual(result["revision_records"], 2)
        self.assertEqual(result["missing_records"], 1)

    def test_overlapping_revisions_fail(self):
        with self.assertRaises(ValueError):
            archive_stats(archive("2020-01-01,1,2020-02-01,2020-02-29\n2020-01-01,2,2020-02-29,\n"), "TEST", "2020-01-01", "2020-02-29", ["2020-02-01", "2020-02-29"])

    def test_future_release_and_outside_requested_vintages_fail(self):
        for rows in ("2020-01-01,1,2020-03-01,\n", "2020-01-01,1,2020-02-02,2020-02-03\n"):
            with self.assertRaises(ValueError):
                archive_stats(archive(rows), "TEST", "2020-01-01", "2020-02-29", ["2020-02-01", "2020-02-29"])

    def test_vintage_field_is_read_from_form(self):
        form = DownloadForm()
        form.feed('<select id="form_selected_vintage_dates" name="form[selected_vintage_dates][]"><option value="2020-01-01">Date</option></select><select><option value="csv">CSV</option></select>')
        self.assertEqual(form.vintages, ["2020-01-01"])
        self.assertEqual(form.vintage_name, "form[selected_vintage_dates][]")

    def test_month_end_grid_includes_leap_day_and_exact_cutoff(self):
        self.assertEqual(month_ends("2020-01-15", "2020-03-15"),
                         ["2020-01-15", "2020-01-31", "2020-02-29", "2020-03-15"])

    def test_snapshot_wrong_vintage_fails(self):
        with self.assertRaises(ValueError):
            snapshot_stats(b"observation_date,TEST_20200201\n2020-01-01,1\n", "TEST", ["2020-01-31"], "2020-01-01", "2020-02-29")

    def test_snapshot_future_value_is_quarantined_not_counted(self):
        result = snapshot_stats(b"observation_date,TEST_20200131\n2020-01-01,1\n2020-02-01,2\n", "TEST", ["2020-01-31"], "2020-01-01", "2020-02-29")
        self.assertEqual(result["eligible_numeric_observations_by_vintage"], {"TEST_20200131": 1})
        self.assertEqual(result["quarantined_future_observations"][0]["observation_date"], "2020-02-01")

    def test_snapshot_keeps_each_columns_own_information_cutoff(self):
        result = snapshot_stats(b"observation_date,TEST_20200131,TEST_20200229\n2020-01-01,1,2\n2020-02-01,,3\n", "TEST", ["2020-01-31", "2020-02-29"], "2020-01-01", "2020-02-29")
        self.assertEqual(result["eligible_numeric_observations_by_vintage"], {"TEST_20200131": 1, "TEST_20200229": 2})


if __name__ == "__main__":
    unittest.main()
