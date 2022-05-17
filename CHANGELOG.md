# Changelog


## Unreleased
### Added
- `pypi release` support for poetry based projects (#27)
- `version tag/bump` support for poetry based projects (#27)
- `semver2` plugin (#20)`
- `remote` config attribute for repository plugins
### Fixed
- version plugins no longer mangle pyproject.toml formatting (#35)
- git plugin will now always set remote and branch for pull and push
- semver2 plugin always trying to tag a prerelease during bump action (#39)
- changelog version sorting issues during generate and release (#38)
- template plugin will now copy file permissions (#37)
### Removed
- version plugin: automatic creation of dev tags (#46)


## 1.0.0
### Added
- python 3.7 support (#15)
- python 3.8 support (#19)
- python 3.9 support (#19)
### Fixed
- version plugin: bump needs to do a pull before changelog validation (#14)
- venv plugin: copy: remove *.pyc files after copying a venv (#17)
- venv plugin: sync_setup --freeze option added
- venv plugin: sync_setup now also generates dev packages into extra_requires
- issue in setup.py with download_url and url (#18)
### Removed
- venv plugin is no longer working (due to poetry not allowing bash scripts and it no longer being used)
- python2.7 support (#21)
- python3.4 support (#21)
- python3.5 support (#21)


## 0.3.1
### Changed
- switch to confu package, away from cfu (same version and codebase, different package name)
- update test requirements for pyaml according to python version


## 0.3.0
### Added
- `venv` plugin: `sync_setup` operation added
- `confuargparserouter`: better way to route confu generated cli parameters to sub parsers
- `changelog` plugin`
- `version` plugin: changelog validation
### Fixed
- fix #13: plugin.expose_vars: don't raise on io error
- fix #5: fix config error handling for errors that happen outside of plugin config
- fix #6: fix semantic version bumping when the current version is truncated


## 0.2.0
### Changed
- pypi plugin: config `repository` changed to `pypi_repository` (#2)
- pypi plugin: config `target` changed to `repository` (#2)