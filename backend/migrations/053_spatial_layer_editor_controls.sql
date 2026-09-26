ALTER TABLE navigation_space_layers_current
ADD COLUMN textured INTEGER NOT NULL DEFAULT 1 CHECK(textured IN (0,1));

ALTER TABLE navigation_space_layers_current
ADD COLUMN editable INTEGER NOT NULL DEFAULT 1 CHECK(editable IN (0,1));
