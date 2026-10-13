use fff_ai_abi::*;
fn wait(_: &ObservationView<'_>) -> CtfTeamAction {
    CtfTeamAction::waits()
}
fff_ai_abi::export_ai!(wait);
