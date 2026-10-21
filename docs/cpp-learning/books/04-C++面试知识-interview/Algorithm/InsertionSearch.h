//插值查找
int InsertionSearch(int a[], int value, int low, int high)
{
    if (low > high || value < a[low] || value > a[high])
        return -1;                                  // 区间无效或值不可能在区间内，查找失败
    if (a[high] == a[low])                          // 区间两端元素相等，防止除零
        return a[low] == value ? low : -1;

    // 先乘后除，避免整数除法中途截断导致 mid 退化
    int mid = low + (value - a[low]) * (high - low) / (a[high] - a[low]);

    if (a[mid] == value)
        return mid;
    if (a[mid] > value)
        return InsertionSearch(a, value, low, mid - 1);
    if (a[mid] < value)
        return InsertionSearch(a, value, mid + 1, high);
}