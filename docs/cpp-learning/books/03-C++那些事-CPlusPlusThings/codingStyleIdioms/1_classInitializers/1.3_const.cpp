/* 1.3_类中const数据成员、引用数据成员.cpp */
//
// Created by light on 19-12-9.
//

#include <iostream>

class Animal {
public:
    Animal(int& age,std::string name):age_(age),name_(name) {
        std::cout << "Animal(int age) is called" << std::endl;
    }
private:
    int &age_;
    const std::string name_;
};

int main() {
    int x = 10;
    Animal animal(x,"hh");
    return 0;
}