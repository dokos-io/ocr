# Test records created once, before any eTransactions test runs — needed by tests
# (e.g. the entity resolver's buyer-VAT guard) that depend on a Company existing
# regardless of module run order.
global_test_dependencies = ["Company"]
