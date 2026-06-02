import pytest
from src.scheduler.models import SporadicTask, AperiodicTask
from src.scheduler.acceptance_tester import AcceptanceTester

@pytest.fixture
def base_slack():
    # 72 小時，每個小時 10 MWh 餘裕
    slack = [10] * 72
    # 刻意在 t=5 製造斷層
    slack[5] = 0
    return slack

def test_sporadic_preempt_1(base_slack):
    tester = AcceptanceTester(base_slack)
    s1 = SporadicTask(id="S1", r=0, e=2, w=5, preempt=1, d=10)
    
    assert tester.test_sporadic(s1, current_t=0) is True
    assert tester.online_schedule["S1"] == [0, 1]
    assert tester.slack_capacity[0] == 5
    assert tester.slack_capacity[1] == 5

def test_sporadic_preempt_0_crosses_gap(base_slack):
    tester = AcceptanceTester(base_slack)
    # t=5 是 0，所以 [3, 6] 無法成立，必須往後找到 [6, 9]
    s2 = SporadicTask(id="S2", r=3, e=4, w=6, preempt=0, d=10)
    
    assert tester.test_sporadic(s2, current_t=3) is True
    assert tester.online_schedule["S2"] == [6, 7, 8, 9]
    assert tester.slack_capacity[6] == 4

def test_aperiodic_preempt_1_impossible(base_slack):
    tester = AcceptanceTester(base_slack)
    # w=15 超過所有小時的 max slack (10)，絕對排不進去
    a1 = AperiodicTask(id="A1", r=10, e=20, w=15, preempt=1, d=None)
    
    assert tester.test_aperiodic(a1, current_t=10) is False
    assert len(tester.aperiodic_queue) == 0

def test_aperiodic_preempt_0_queue_and_backfill(base_slack):
    tester = AcceptanceTester(base_slack)
    
    # A2 需求連續 2 小時，w=8
    a2 = AperiodicTask(id="A2", r=10, e=2, w=8, preempt=0, d=None)
    assert tester.test_aperiodic(a2, current_t=10) is True
    assert len(tester.aperiodic_queue) == 1
    
    # A3 需求 2 小時 (可離散)，w=8
    a3 = AperiodicTask(id="A3", r=10, e=2, w=8, preempt=1, d=None)
    assert tester.test_aperiodic(a3, current_t=10) is True
    assert len(tester.aperiodic_queue) == 2
    
    # 推進到 t=10
    tester.process_queue_at_tick(current_t=10)
    # A2 發現 [10, 11] 有連續 10 的 slack，直接整併！
    assert tester.online_schedule["A2"] == [10, 11]
    # 此時 t=10 的 slack 只剩 2，A3 (w=8) 吃不下，所以 A3 會留在 Queue 裡面
    assert len(tester.aperiodic_queue) == 1
    assert tester.aperiodic_queue[0].task.id == "A3"
    
    # 推進到 t=11
    tester.process_queue_at_tick(current_t=11)
    # t=11 的 slack 也只剩 2 (被 A2 吃掉)，A3 繼續等
    assert "A3" not in tester.online_schedule
    
    # 推進到 t=12
    tester.process_queue_at_tick(current_t=12)
    # t=12 的 slack 是 10，A3 (Preempt=1) 吃下 1 小時！
    assert tester.online_schedule["A3"] == [12]
    assert len(tester.aperiodic_queue) == 1
    
    # 推進到 t=13
    tester.process_queue_at_tick(current_t=13)
    # A3 再吃下 1 小時，執行完畢！
    assert tester.online_schedule["A3"] == [12, 13]
    assert len(tester.aperiodic_queue) == 0
