#include <iostream>
using namespace std;

int main() {
  const int p = 10;
  // const void *vp = &p;  // const pointer to const data
  void *vp = (void*)&p; // ✅ C-style cast
}
