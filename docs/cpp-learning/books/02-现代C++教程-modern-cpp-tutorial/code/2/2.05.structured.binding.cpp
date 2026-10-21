//
// 2.5.structured.binding.cpp
// chapter 2 language usability
// modern cpp tutorial
//
// created by changkun at changkun.de
// https://github.com/changkun/modern-cpp-tutorial
//

#include <iostream>
#include <tuple>
#include <string>
#include <map>

std::tuple<int, double, std::string> f() {
    return std::make_tuple(1, 2.3, "456");
}

int main() {
    // Unpack a tuple straight into named variables.
    auto [x, y, z] = f();
    std::cout << x << ", " << y << ", " << z << std::endl;

    // Bind each key/value pair while iterating an associative container,
    // instead of writing it->first / it->second.
    std::map<std::string, int> scores{{"alice", 90}, {"bob", 80}};
    for (const auto& [name, score] : scores) {
        std::cout << name << ": " << score << '\n';
    }
    return 0;
}
