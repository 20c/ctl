import re


def version_tuple(version):
    """Returns a tuple from version string"""
    if isinstance(version, tuple):
        return version
    return tuple(version.split("."))


def version_string(version):
    """Returns a string from version tuple or list"""
    if isinstance(version, str):
        return version
    return ".".join([f"{v}" for v in version])


def validate_prerelease(prerelease):
    if not isinstance(prerelease, (list, tuple)):
        prerelease = list(prerelease.split("."))

    for identifier in prerelease:
        if identifier == "":
            raise ValueError("Identifiers must not be empty")

        regex = r"[0-9A-Za-z-]+"
        match = re.match(regex, identifier)
        if not bool(match):
            raise ValueError(
                "Prerelease identifier must comprise only ASCII alphanumerics and hyphens"
            )

        regex = r"^0[0-9]+"
        match = re.match(regex, identifier)
        if bool(match):
            raise ValueError("Numeric identifiers must not have leading zeroes")

    # If the last part of the prerelease does not end with number
    # we want to append ".1" so we can bump in the future
    if not re.match(r".*[0-9]$", prerelease[-1]):
        prerelease.append("1")

    return ".".join(prerelease)


def validate_semantic(version, pad=0):
    if not isinstance(version, (list, tuple)):
        version = version_tuple(version)

    parts = len(version)

    if parts < 1:
        raise ValueError("Semantic version needs to contain at least a major version")
    if parts > 4:
        raise ValueError("Semantic version can not contain more than 4 parts")

    if parts < pad:
        version = tuple(list(version) + [0 for i in range(0, pad - parts)])

    return tuple([int(n) for n in version])


def bump_semantic(version, segment):
    if segment == "major":
        version = list(validate_semantic(version))
        return (version[0] + 1, 0, 0)
    elif segment == "minor":
        version = list(validate_semantic(version, pad=2))
        return (version[0], version[1] + 1, 0)
    elif segment == "patch":
        version = list(validate_semantic(version, pad=3))
        return (version[0], version[1], version[2] + 1)
    elif segment == "dev":
        version = list(validate_semantic(version, pad=4))
        try:
            return (version[0], version[1], version[2], version[3] + 1)
        except IndexError:
            return (version[0], version[1], version[2], 1)
