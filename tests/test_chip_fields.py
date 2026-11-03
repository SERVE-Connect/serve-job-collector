import os, sys, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import collector


def job(**o):
    j = {"title": "Associate", "requirements": "", "section": "IT / Software", "city_group": "Pune", "also_in": []}
    j.update(o)
    return j


class ChipFields(unittest.TestCase):
    def test_it_job_has_no_keyword_domain(self):
        f = collector.chip_fields(job(title="Pharma Data Engineer"))
        self.assertEqual(f["domains"], [])  # keyword domains only apply to Non-IT / Clinical, like the ranked lists

    def test_keyword_domains_match_title_and_requirements(self):
        f = collector.chip_fields(job(section="Non-IT / Other", title="Hotel Front Office Executive", requirements="sales targets"))
        self.assertEqual(f["domains"], ["Hospitality", "Sales & Marketing"])

    def test_multi_city_and_internship(self):
        f = collector.chip_fields(job(also_in=["Mumbai, India", "Pune"], title="Software Intern"))
        self.assertEqual(f["cities"], ["Pune", "Mumbai"])
        self.assertTrue(f["internship"])
        self.assertFalse(collector.chip_fields(job(title="Internal Auditor"))["internship"])


if __name__ == "__main__":
    unittest.main()
