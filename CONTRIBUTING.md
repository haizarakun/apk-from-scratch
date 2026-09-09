# Contributing

Thanks for your interest. This project values small, correct, readable
contributions over large ones.

## Principles

- **Correctness is checked against real tooling.** Every format this project
  writes is validated by an independent parser (androguard) and, for
  signatures, by a cryptographic verifier. A change to any writer must keep
  `python3 tests/test_build.py` green.
- **Readable by anyone.** Names, comments, and structure should make the byte
  layout auditable against the referenced specifications. Prefer a clear
  function over a clever one.
- **No heavyweight dependencies.** The build path uses only the standard
  library plus `cryptography` for signing. Tests may use `androguard`.

## Development

```bash
pip install -r requirements.txt
python3 examples/counter/build.py     # build something
python3 -m apkfs.verify examples/counter/counter.apk
python3 tests/test_build.py           # must pass
```

## Pull requests

- Keep each PR focused on one change.
- Add or extend a test that fails before your change and passes after.
- Update `CHANGELOG.md` under "Unreleased".
- Explain *why* a byte layout is the way it is if it is not obvious; cite the
  relevant part of the format spec in a comment.

## Good first issues

- Add more Dalvik instructions to `apkfs/dalvik.py` with encoders and a test.
- Support a second density bucket for the icon in `resources.arsc`.
- Add `uses-permission` support to the manifest builder.
