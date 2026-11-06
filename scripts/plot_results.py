import pandas as pd
import matplotlib.pyplot as plt
from pathlib import Path

def plot_benchmark():
    file_path = Path("results/benchmark.csv")
    if not file_path.exists():
        print(f"Không tìm thấy file {file_path}. Hãy đảm bảo bạn chạy file benchmark.py trước.")
        return

    # Đọc dữ liệu
    df = pd.read_csv(file_path)
    
    # Tính median latency theo từng database
    summary = df.groupby('database')['latency_ms'].median().reset_index()

    # Khởi tạo biểu đồ
    plt.figure(figsize=(8, 6))
    bars = plt.bar(summary['database'], summary['latency_ms'], color=['#3498db', '#e74c3c'])
    
    # Định dạng trực quan
    plt.title('So sánh Median Latency: Cassandra vs ClickHouse\n(Lưu ý: Hai workload hoàn toàn khác biệt)', 
              fontsize=14, pad=15)
    plt.ylabel('Median Latency (ms)', fontsize=12)
    plt.xlabel('Cơ sở dữ liệu', fontsize=12)
    
    # Gắn số liệu trực tiếp lên đầu mỗi cột
    for bar in bars:
        yval = bar.get_height()
        plt.text(bar.get_x() + bar.get_width()/2, yval + 0.05, 
                 f"{yval:.2f} ms", ha='center', va='bottom', 
                 fontsize=12, fontweight='bold')

    # Xử lý lưu file
    out_dir = Path("results")
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / "latency_chart.png"
    plt.savefig(out_path, dpi=300, bbox_inches='tight')
    print(f"Đã vẽ xong! Biểu đồ được lưu tại: {out_path}")

if __name__ == "__main__":
    plot_benchmark()
