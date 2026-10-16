import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/update_contributions.py'
SPEC = importlib.util.spec_from_file_location('updater', SCRIPT)
updater = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(updater)


def pull(number=1, repository='community/project', merged='2026-10-16T13:10:02Z'):
    url = f'https://github.com/{repository}'
    return {
        'number': number, 'title': 'Fix a real problem', 'url': f'{url}/pull/{number}',
        'mergedAt': merged, 'author': {'login': 'Avaivartika'},
        'repository': {
            'nameWithOwner': repository, 'url': url, 'isPrivate': False,
            'isFork': False, 'owner': {'login': repository.split('/')[0]},
            'description': 'A public project',
        },
    }


def page(nodes, cursor=None):
    return {'data': {'user': {'pullRequests': {
        'nodes': nodes, 'pageInfo': {'hasNextPage': cursor is not None, 'endCursor': cursor},
    }}}}


class ContributionTests(unittest.TestCase):
    def test_private_unmerged_personal_and_other_authors_are_excluded(self):
        private = pull(repository='private-org/secret-project')
        private['repository']['isPrivate'] = True
        fork = pull(repository='somebody/fork')
        fork['repository']['isFork'] = True
        other = pull()
        other['author']['login'] = 'someone-else'
        for node in [private, fork, other, pull(merged=None), pull(repository='avaivartika/personal')]:
            with self.subTest(node=node):
                self.assertIsNone(updater.public_contribution(node, 'Avaivartika'))

    def test_pagination_collects_old_and_new_merges_and_deduplicates(self):
        recent, old = pull(2), pull(1, merged='2020-01-01T00:00:00Z')
        seen = []

        def api(query, variables):
            seen.append(variables['cursor'])
            return page([old], 'page-two') if variables['cursor'] is None else page([recent, old])

        records = updater.fetch_contributions('Avaivartika', api)
        self.assertEqual(seen, [None, 'page-two'])
        self.assertEqual([r['number'] for r in records], [2, 1])

    def test_private_fields_never_enter_public_output(self):
        private = pull(repository='private-org/do-not-publish')
        private['repository']['isPrivate'] = True
        records = updater.fetch_contributions('Avaivartika', lambda *args: page([private, pull()]))
        published = json.dumps(records) + updater.render_profile(records, {'username': 'Avaivartika'})
        self.assertNotIn('do-not-publish', published)
        self.assertNotIn('private-org', published)

    def test_graphql_failure_does_not_accept_partial_results(self):
        response = page([pull()])
        response['errors'] = [{'message': 'Partial data'}]
        with self.assertRaises(RuntimeError):
            updater.fetch_contributions('Avaivartika', lambda *args: response)

    def test_pagination_loop_stops_without_publishing_partial_results(self):
        with self.assertRaises(RuntimeError):
            updater.fetch_contributions('Avaivartika', lambda *args: page([pull()], 'same-cursor'))

    def test_untrusted_urls_cannot_be_published(self):
        node = pull()
        node['url'] = 'https://example.com/not-a-pull-request'
        with self.assertRaises(ValueError):
            updater.public_contribution(node, 'Avaivartika')

    def test_upstream_html_is_escaped(self):
        node = pull()
        node['title'] = '<img src=x onerror="alert(1)">'
        records = [updater.public_contribution(node, 'Avaivartika')]
        rendered = updater.render_profile(records, {'username': 'Avaivartika'})
        self.assertNotIn('<img', rendered)
        self.assertIn('&lt;img', rendered)

    def test_profile_has_one_entry_per_repo_and_archive_keeps_every_pr(self):
        records = [updater.public_contribution(pull(n), 'Avaivartika') for n in (1, 2)]
        config = {'username': 'Avaivartika'}
        profile = updater.render_profile(records, config)
        archive = updater.render_archive(records, config)
        self.assertEqual(profile.count('<table'), 1)
        self.assertIn('2 merged contributions', profile)
        for number in (1, 2):
            self.assertIn(f'/pull/{number}', archive)

    def test_custom_intro_and_footer_survive_refresh(self):
        original = f'My own introduction\n{updater.START}\nold\n{updater.END}\nMy own footer'
        result = updater.replace_section(original, 'new contribution')
        self.assertEqual(result, f'My own introduction\n{updater.START}\n\nnew contribution\n\n{updater.END}\nMy own footer')

    def test_missing_duplicate_or_reversed_markers_fail(self):
        for readme in ['', updater.START * 2 + updater.END, updater.END + updater.START]:
            with self.subTest(readme=readme), self.assertRaises(ValueError):
                updater.replace_section(readme, 'new')

    def test_curated_summaries_are_used_without_rewriting_config(self):
        config = {'username': 'Avaivartika', 'repositories': {'community/project': {
            'name': 'Project', 'summaries': {'1': 'A carefully written summary.'},
        }}}
        original = copy.deepcopy(config)
        records = [updater.public_contribution(pull(), 'Avaivartika')]
        self.assertIn('A carefully written summary.', updater.render_profile(records, config))
        self.assertEqual(original, config)

    def test_disappearing_history_requires_explicit_confirmation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'data').mkdir()
            (root / 'README.md').write_text(updater.START + '\n' + updater.END)
            records = [updater.public_contribution(pull(), 'Avaivartika')]
            (root / 'data/contributions.json').write_text(json.dumps({'contributions': records}))
            with self.assertRaises(RuntimeError):
                updater.build_outputs(root, [], {'username': 'Avaivartika'})
            self.assertEqual(json.loads((root / 'data/contributions.json').read_text())['contributions'], records)
            outputs = updater.build_outputs(root, [], {'username': 'Avaivartika'}, allow_removals=True)
            self.assertEqual(json.loads(outputs[root / 'data/contributions.json'])['contributions'], [])

    def test_unchanged_input_produces_identical_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'README.md').write_text(updater.START + '\n' + updater.END)
            records = [updater.public_contribution(pull(), 'Avaivartika')]
            config = {'username': 'Avaivartika'}
            first = updater.build_outputs(root, records, config)
            for path, content in first.items():
                path.parent.mkdir(exist_ok=True)
                path.write_text(content)
            self.assertEqual(updater.build_outputs(root, records, config), first)


if __name__ == '__main__':
    unittest.main()
