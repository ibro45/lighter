from pathlib import Path

import torch

from lighter.callbacks.writer.table import LighterTableWriter


def test_table_writer_initialization():
    writer = LighterTableWriter(path="test.csv", writer="tensor")
    assert writer.path == Path("test.csv")


def test_table_writer_write():
    """Test LighterTableWriter write functionality with various inputs."""
    test_file = Path("test.csv")
    writer = LighterTableWriter(path="test.csv", writer="tensor")
    
    # Test basic write
    test_tensor = torch.tensor([1, 2, 3])
    writer.write(tensor=test_tensor, id=1)
    assert len(writer.csv_records) == 1
    assert writer.csv_records[0]["tensor"] == test_tensor.tolist()
    assert writer.csv_records[0]["id"] == 1
    
    # Test edge cases
    writer.write(tensor=torch.tensor([]), id=2)  # empty tensor
    writer.write(tensor=torch.randn(1000), id=3)  # large tensor
    writer.write(tensor=torch.tensor([1.5, 2.5]), id=4)  # float tensor
    
    # Verify file creation and content
    assert test_file.exists()
    with open(test_file) as f:
        content = f.read()
        assert "1,2,3" in content  # verify first tensor
    
    # Cleanup
    test_file.unlink()
