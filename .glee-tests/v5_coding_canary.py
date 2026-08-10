from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AcceptanceSnapshot:
    v5_http_status: int
    github_write_verified: bool
    public_site_http_status: int

    @property
    def v5_paired(self) -> bool:
        return self.v5_http_status != 401

    @property
    def independent_coding_path_healthy(self) -> bool:
        return self.github_write_verified

    @property
    def public_site_reachable(self) -> bool:
        return 200 <= self.public_site_http_status < 400


def summarize(snapshot: AcceptanceSnapshot) -> dict[str, bool]:
    return {
        "v5_paired": snapshot.v5_paired,
        "github_write_verified": snapshot.independent_coding_path_healthy,
        "public_site_reachable": snapshot.public_site_reachable,
    }


def _self_test() -> None:
    observed = summarize(AcceptanceSnapshot(401, True, 200))
    expected = {
        "v5_paired": False,
        "github_write_verified": True,
        "public_site_reachable": True,
    }
    assert observed == expected, (observed, expected)
    print("GLEE V5 coding canary: PASS")


if __name__ == "__main__":
    _self_test()
