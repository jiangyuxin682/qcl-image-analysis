import pytest

from qcl_analysis.metadata import index_qcl_dataset


def test_index_qcl_dataset(tmp_path):
    stacks = tmp_path / "stacks"

    pattern0 = stacks / "pattern0"
    pattern1 = stacks / "pattern1"

    pattern0.mkdir(parents=True)
    pattern1.mkdir()

    # Create fake QCL files
    (pattern0 / "lineScan_1600_0invcm.csv").touch()
    (pattern0 / "lineScan_1655_0invcm.csv").touch()
    (pattern1 / "lineScan_1600_0invcm.csv").touch()
    (pattern1 / "lineScan_1655_0invcm.csv").touch()

    dataset = index_qcl_dataset(stacks)

    assert len(dataset) == 4

    assert dataset["frame"].tolist() == [0, 0, 1, 1]
    assert dataset["wavenumber"].tolist() == [1600, 1655, 1600, 1655]


def test_no_valid_qcl_files_raises_error(tmp_path):
    stacks = tmp_path / "stacks"
    stacks.mkdir()

    with pytest.raises(ValueError):
        index_qcl_dataset(stacks)
