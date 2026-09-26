-- Add explicit random-encounter trigger semantics.
-- Distance policies cover travel through terrain/regions/roads.
-- Transition policies cover doors/routes/connectors whose old behavior rolled
-- once per traversal rather than according to geometric distance.

ALTER TABLE navigation_encounter_policies_current
ADD COLUMN trigger_kind TEXT NOT NULL DEFAULT 'distance'
CHECK(trigger_kind IN ('distance','transition'));

ALTER TABLE navigation_encounter_policies_current
ADD COLUMN probability_per_transition REAL
CHECK(
  probability_per_transition IS NULL
  OR (probability_per_transition >= 0 AND probability_per_transition <= 1)
);
