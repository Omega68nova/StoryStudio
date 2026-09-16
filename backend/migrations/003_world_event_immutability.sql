CREATE TRIGGER world_events_no_update
BEFORE UPDATE ON world_events
BEGIN
    SELECT RAISE(ABORT, 'world events are immutable');
END;

CREATE TRIGGER world_transactions_no_update
BEFORE UPDATE ON world_transactions
BEGIN
    SELECT RAISE(ABORT, 'world transactions are immutable');
END;
