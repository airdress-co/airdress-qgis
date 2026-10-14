# Contributing

- Tests first: a behaviour change comes with a test that failed before it.
- Import Qt only through `qgis.PyQt` (`scripts/check-qt-imports.py`).
- No dependency outside the standard library and what QGIS ships.
- Commits are conventional (`feat:`, `fix:`, `docs:` …); pull requests are
  rebased, never merged.

## Run your working copy in QGIS

Link the plugin folder in your QGIS profile to `airdress_qgis/` in this
repository, so QGIS loads the code you have checked out:

1. Close QGIS.
2. Find the profile folder: *Settings → User Profiles → Open Active
   Profile Folder*. The plugins live in `python/plugins/` inside it, for
   example `~/.local/share/QGIS/QGIS3/profiles/default/python/plugins` on
   Linux and `~/Library/Application Support/QGIS/QGIS3/profiles/default/python/plugins`
   on macOS.
3. If an installed copy is there, move it out of `plugins/`. Keep the
   folder name `airdress_qgis` for the link, so the plugin stays enabled
   and stays signed in.
4. Create the link:

   ```sh
   # Linux and macOS
   ln -s "$PWD/airdress_qgis" "<profile>/python/plugins/airdress_qgis"
   ```

   ```bat
   :: Windows: a junction needs no administrator rights
   mklink /J "<profile>\python\plugins\airdress_qgis" "%CD%\airdress_qgis"
   ```

5. Start QGIS and check *Plugins → Manage and Install Plugins →
   Installed*: Airdress shows the version in `airdress_qgis/metadata.txt`.

From then on, QGIS runs whatever this clone has checked out. That means a
`git pull` on `main` updates it, and switching to a branch runs that
branch. Restart QGIS after a change; QGIS loads a plugin's Python only
once.

To go back to a release, remove the link (`rm` the link itself, or
`rmdir` the junction; neither touches the repository). Then install the
zip from the release page with *Install from ZIP*.

## Tests

The unit tests run in the official QGIS images, as CI runs them:

```sh
for v in 3.44 4.2; do
  docker run --rm -e QT_QPA_PLATFORM=offscreen -v "$PWD:/w" -w /w qgis/qgis:$v \
    sh -c 'python3 -m pip install -q --break-system-packages pytest-cov &&
           python3 -m pytest -q -p no:cacheprovider --cov=airdress_qgis --cov-fail-under=90 tests'
done
```

`e2e/live.py` drives the plugin against the live service in a QGIS with
no window, and needs an account past the waitlist. It opens your browser
for the sign-in:

```sh
QT_QPA_PLATFORM=offscreen python3 e2e/live.py
```

Run it with the Python that QGIS uses. Each step prints a `STEP` line, and
the exit code is the verdict.
