from typing import List, Dict
from src.scheduler.models import SporadicTask, AperiodicTask

class QueuedAperiodicTask:
    def __init__(self, task: AperiodicTask):
        self.task = task
        self.wait_ticks = 0

class AcceptanceTester:
    def __init__(self, slack_capacity: List[int]):
        """
        slack_capacity: length 72 array containing available slack at each hour.
        """
        self.slack_capacity = list(slack_capacity)
        self.aperiodic_queue: List[QueuedAperiodicTask] = []
        self.aperiodic_task_registry: Dict[str, QueuedAperiodicTask] = {}
        self.online_schedule: Dict[str, List[int]] = {}
        self.rejected_sporadic_this_tick: List[str] = []

    def test_sporadic(self, task: SporadicTask, current_t: int) -> bool:
        """
        Conservative Admission Control for Sporadic Tasks.
        O(N) scan.
        Returns True if accepted and scheduled, False if rejected.
        """
        window_start = max(current_t, task.r)
        window_end = min(72, task.r + task.d)
        
        if window_start >= window_end:
            self.rejected_sporadic_this_tick.append(task.id)
            return False

        if task.preempt == 1:
            reserved_hours = []
            for k in range(window_start, window_end):
                if self.slack_capacity[k] >= task.w:
                    reserved_hours.append(k)
                    if len(reserved_hours) == task.remaining_execution:
                        break
                        
            if len(reserved_hours) == task.remaining_execution:
                for k in reserved_hours:
                    self.slack_capacity[k] -= task.w
                self.online_schedule[task.id] = reserved_hours
                task.is_completed = True
                task.remaining_execution = 0
                return True
            else:
                self.rejected_sporadic_this_tick.append(task.id)
                return False

        else:
            consecutive_count = 0
            for k in range(window_start, window_end):
                if self.slack_capacity[k] >= task.w:
                    consecutive_count += 1
                    if consecutive_count == task.remaining_execution:
                        reserved_hours = list(range(k - task.remaining_execution + 1, k + 1))
                        for h in reserved_hours:
                            self.slack_capacity[h] -= task.w
                        self.online_schedule[task.id] = reserved_hours
                        task.is_completed = True
                        task.remaining_execution = 0
                        return True
                else:
                    consecutive_count = 0
                    
            self.rejected_sporadic_this_tick.append(task.id)
            return False

    def test_aperiodic(self, task: AperiodicTask, current_t: int) -> bool:
        """
        Strict Admissibility Pre-check for Aperiodic Tasks.
        Returns True if admitted into the queue, False if physically impossible (Rejected).
        """
        window_start = max(current_t, task.r)
        window_end = 72
        
        if window_start >= window_end:
            return False
            
        # Strict Admissibility Pre-check
        if task.preempt == 1:
            available_slots = 0
            for k in range(window_start, window_end):
                if self.slack_capacity[k] >= task.w:
                    available_slots += 1
                    if available_slots >= task.remaining_execution:
                        break
            if available_slots < task.remaining_execution:
                return False
        else:
            consecutive_count = 0
            found = False
            for k in range(window_start, window_end):
                if self.slack_capacity[k] >= task.w:
                    consecutive_count += 1
                    if consecutive_count == task.remaining_execution:
                        found = True
                        break
                else:
                    consecutive_count = 0
            if not found:
                return False
                
        # Passed pre-check, add to queue
        q_task = QueuedAperiodicTask(task)
        self.aperiodic_task_registry[task.id] = q_task
        self.aperiodic_queue.append(q_task)
        return True

    def defer_aperiodic_execution(self, task_id: str, current_t: int) -> bool:
        """
        Cancel an aperiodic execution at current_t and restore the task to the
        aperiodic queue for future scheduling. Returns True if the task was
        found and rescheduled state was restored.
        """
        q_task = self.aperiodic_task_registry.get(task_id)
        if q_task is None:
            return False

        scheduled_hours = self.online_schedule.get(task_id, [])
        removed_hours = [h for h in scheduled_hours if h >= current_t]
        if not removed_hours:
            return False

        task = q_task.task
        self.online_schedule[task_id] = [h for h in scheduled_hours if h < current_t]
        if not self.online_schedule[task_id]:
            del self.online_schedule[task_id]

        for h in removed_hours:
            if 0 <= h < len(self.slack_capacity):
                self.slack_capacity[h] += task.w

        task.remaining_execution += len(removed_hours)
        task.is_completed = False

        if all(existing.task.id != task_id for existing in self.aperiodic_queue):
            self.aperiodic_queue.append(q_task)
        return True

    def process_queue_at_tick(self, current_t: int) -> List[str]:
        """
        Processes the aperiodic queue at the given tick.
        Handles Drop conditions, Partial Execution, and Backfilling.
        Returns a list of task IDs that were dropped (missed_aperiodic).
        """
        # 1. Update wait_ticks and perform Drops
        new_queue = []
        dropped_tasks = []
        for q_task in self.aperiodic_queue:
            q_task.wait_ticks += 1
            
            # Timeout Drop (wait > 24 hours)
            if q_task.wait_ticks > 24:
                dropped_tasks.append(q_task.task.id)
                continue
                
            # Dynamic Impossibility Drop
            if q_task.task.remaining_execution > (72 - current_t):
                dropped_tasks.append(q_task.task.id)
                continue
                
            new_queue.append(q_task)
            
        self.aperiodic_queue = new_queue
        
        # 2. Try to schedule tasks in the queue at current_t
        final_queue = []
        for q_task in self.aperiodic_queue:
            task = q_task.task
            
            if task.preempt == 1:
                if self.slack_capacity[current_t] >= task.w:
                    # Execute 1 hour (Partial Execution)
                    self.slack_capacity[current_t] -= task.w
                    task.remaining_execution -= 1
                    
                    if task.id not in self.online_schedule:
                        self.online_schedule[task.id] = []
                    self.online_schedule[task.id].append(current_t)
                    
                    if task.remaining_execution == 0:
                        task.is_completed = True
                    else:
                        final_queue.append(q_task)
                else:
                    # Backfill next task
                    final_queue.append(q_task)
            else:
                # preempt == 0: Must run as a contiguous block starting at current_t
                if current_t + task.remaining_execution <= 72:
                    can_schedule = True
                    for k in range(current_t, current_t + task.remaining_execution):
                        if self.slack_capacity[k] < task.w:
                            can_schedule = False
                            break
                            
                    if can_schedule:
                        # Schedule the entire block
                        reserved = list(range(current_t, current_t + task.remaining_execution))
                        for h in reserved:
                            self.slack_capacity[h] -= task.w
                        self.online_schedule[task.id] = reserved
                        task.is_completed = True
                        task.remaining_execution = 0
                    else:
                        # Backfill next task
                        final_queue.append(q_task)
                else:
                    # Will be dropped next tick by Dynamic Impossibility
                    final_queue.append(q_task)
                    
        self.aperiodic_queue = final_queue
        return dropped_tasks
