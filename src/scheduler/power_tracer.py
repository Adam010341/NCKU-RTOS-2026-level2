from typing import Dict, List, Tuple, Any

def trace_power_flows(
    active_jobs: List[Any], 
    generators: List[Any], 
    battery_discharges: Dict[str, float], 
    renewable_outputs: Dict[str, float]
) -> Tuple[Dict[str, Dict[str, float]], float]:
    """
    能量流分配演算法 (Water-filling Power Tracing)
    
    依據 Constraint 1 與 23，將當前小時各供電設備實際發出的總電能 (P)，
    精準配對並注水到各個執行任務的杯子中 (k)，最終消耗不完的剩餘電能流向市場 (sell)。
    
    優先序: 綠電 (成本0) -> 傳統機組基載 -> 儲能放電
    """
    # 1. 建立當前時段的供電源水桶 (Supply Pool)
    supply_pool = {}
    
    # 納入綠電 (最優先)
    for r_id, r_out in renewable_outputs.items():
        if r_out > 0:
            supply_pool[r_id] = float(r_out)
            
    # 納入傳統機組當前出力
    for gen in generators:
        if gen.current_output > 0:
            supply_pool[gen.id] = float(gen.current_output)
            
    # 納入電池實際放電量
    for b_id, b_dis in battery_discharges.items():
        if b_dis > 0:
            supply_pool[b_id] = float(b_dis)

    # 2. 建立任務電量需求對照表 (Consumers)
    k_matrix = {job.id: {} for job in active_jobs}
    
    # 3. 雙層注水邏輯 (Water-filling Loop)
    for job in active_jobs:
        remaining_demand = float(job.w)
        
        for supplier_id in list(supply_pool.keys()):
            available_power = supply_pool[supplier_id]
            if available_power <= 0:
                continue
                
            # 計算本次注水量
            poured = min(remaining_demand, available_power)
            
            # 寫入分配矩陣 k_{j, i, t}
            k_matrix[job.id][supplier_id] = poured
            
            # 扣減水桶與空杯
            supply_pool[supplier_id] -= poured
            remaining_demand -= poured
            
            if remaining_demand <= 0:
                break
                
        # 嚴格約束檢查：如果跑完所有供應商，杯子還沒滿，代表系統發生算力斷層
        if remaining_demand > 0.001:
            raise ValueError(f"【物理違規】時間點能量不平衡！任務 {job.id} 仍有 {remaining_demand} MWh 供電缺口。")

    # 4. 結算全域被迫超發或套利多發的售電量 (Sell)
    # 所有用電杯子裝滿後，發電水桶裡剩下來的水，全部直接排向市場
    total_sell = sum(supply_pool.values())
    
    # 過濾掉矩陣中為 0 的多餘欄位，保持 JSON 報表乾淨
    clean_k = {j_id: {dev: v for dev, v in dev_map.items() if v > 0} for j_id, dev_map in k_matrix.items()}
    
    return clean_k, total_sell