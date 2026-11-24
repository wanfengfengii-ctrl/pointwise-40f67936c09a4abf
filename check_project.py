"""Run this project's full unittest suite from the repository root."""
import sys
import unittest

from overlap_fixture import EXAMPLES, verify_set_fixture


def verify_set_business():
    failures = 0
    for name in EXAMPLES:
        try:
            verify_set_fixture(name)
        except Exception as error:
            failures += 1
            print(f'FAIL set-fixture {name}: {error}')
    total = len(EXAMPLES)
    print(f'V2 SUMMARY fixtures={total} failures={failures} '
          f'result={"PASS" if not failures else "FAIL"}')
    return not failures


def main():
    suite = unittest.defaultTestLoader.discover('tests', top_level_dir='.')
    if suite.countTestCases():
        result = unittest.TextTestRunner(verbosity=2).run(suite)
    else:
        print('No tests discovered in tests/', file=sys.stderr)
        result = unittest.TestResult()
    for status, failed_cases in (
        ('FAIL', (test for test, _ in result.failures)),
        ('ERROR', (test for test, _ in result.errors)),
        ('UNEXPECTED_SUCCESS', result.unexpectedSuccesses),
    ):
        for test in failed_cases:
            print(f'{status} {test.id()}')
    sets_ok = verify_set_business()
    successful = result.testsRun > 0 and result.wasSuccessful() and sets_ok
    print(f'TEST SUMMARY total={result.testsRun} failures={len(result.failures)} '
          f'errors={len(result.errors)} skipped={len(result.skipped)} '
          f'expected_failures={len(result.expectedFailures)} '
          f'unexpected_successes={len(result.unexpectedSuccesses)} '
          f'result={"PASS" if successful else "FAIL"}')
    return 0 if successful else 1


if __name__ == '__main__':
    raise SystemExit(main())
